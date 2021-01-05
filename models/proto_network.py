import coloredlogs
import logging
import os
import pdb
import random
import torch
from tqdm import tqdm
import numpy as np
from datetime import datetime
from torch.utils.tensorboard import SummaryWriter

from models.seq_proto import SeqPrototypicalNetwork
from models.seq_proto_online import SeqPrototypicalOnlineNetwork
from models import utils

logger = logging.getLogger('ProtoLearningLog')
coloredlogs.install(logger=logger, level='DEBUG', fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


class PrototypicalNetwork:
    def __init__(self, config):
        now = datetime.now()
        date_time = now.strftime("%m-%d-%H-%M-%S")
        self.tensorboard_writer = SummaryWriter(log_dir='runs/ProtoNet-' + date_time)
        
        self.base_path = config['base_path']
        self.stamp = config['stamp']
        self.updates = config['num_updates']
        self.meta_epochs = config['num_meta_epochs']
        self.early_stopping = config['early_stopping']
        self.stopping_threshold = config.get('stopping_threshold', 1e-3)

        if 'seq' in config['meta_model']:
            self.proto_model = SeqPrototypicalNetwork(config)
        if 'online' in config['meta_model']:
            self.proto_model = SeqPrototypicalOnlineNetwork(config)

        logger.info('Prototypical network instantiated')

    def training(self, train_episodes, val_episodes):
        best_loss = float('inf')
        best_f1 = 0
        patience = 0
        
        # model_path = os.path.join(self.base_path, 'saved_models', 'Supervised-stable.h5')
        # self.proto_model.learner.load_state_dict(torch.load(model_path))
        
        model_path = os.path.join(self.base_path, 'saved_models', 'ProtoNet-{}.h5'.format(self.stamp))
        logger.info('Model name: ProtoNet-{}.h5'.format(self.stamp))
        
        for epoch in range(self.meta_epochs):
            logger.info('Starting epoch {}/{}'.format(epoch + 1, self.meta_epochs))
            losses, accuracies, precisions, recalls, f1s, _, _ = self.proto_model(train_episodes, 
                                                                                  self.updates)
            avg_loss = np.mean(losses)
            avg_accuracy = np.mean(accuracies)
            avg_precision = np.mean(precisions)
            avg_recall = np.mean(recalls)
            avg_f1 = np.mean(f1s)

            logger.info('Meta train epoch {}: Avg loss = {:.5f}, avg accuracy = {:.5f}, avg precision = {:.5f}, '
                        'avg recall = {:.5f}, avg F1 score = {:.5f}'.format(epoch + 1, avg_loss, avg_accuracy,
                                                                            avg_precision, avg_recall, avg_f1))

            self.tensorboard_writer.add_scalar('Loss/train', avg_loss, global_step=epoch + 1)
            self.tensorboard_writer.add_scalar('F1/train', avg_f1, global_step=epoch + 1)

            losses, _, _, _, _, val_predictions, val_labels = self.proto_model(random.sample(val_episodes, 200), 
                                                                               self.updates, 
                                                                               testing=True)

            accuracy, precision, recall, avg_f1 = utils.calculate_seqeval_metrics(val_predictions,
                                                                                    val_labels, 
                                                                                    tags=val_episodes[0].tags, 
                                                                                    binary=False)
            
            avg_loss = np.mean(losses)

            logger.info('Meta val epoch {}: Avg loss = {:.5f}, avg accuracy = {:.5f}, avg precision = {:.5f}, '
                        'avg recall = {:.5f}, avg F1 score = {:.5f}'.format(epoch + 1, avg_loss, accuracy,
                                                                            precision, recall, avg_f1))

            self.tensorboard_writer.add_scalar('Loss/val', avg_loss, global_step=epoch + 1)
            self.tensorboard_writer.add_scalar('F1/val', avg_f1, global_step=epoch + 1)

            if avg_f1 > best_f1 + self.stopping_threshold:
                patience = 0
                best_loss = avg_loss
                best_f1 = avg_f1
                logger.info('Saving the model since the F1 improved')
                torch.save(self.proto_model.learner.state_dict(), model_path)
                logger.info('')
            else:
                patience += 1
                logger.info('F1 did not improve')
                logger.info('')
                if patience == self.early_stopping:
                    break

            # Log params and grads into tensorboard
            for name, param in self.proto_model.named_parameters():
                if param.requires_grad and param.grad is not None:
                    self.tensorboard_writer.add_histogram('Params/' + name, param.data.view(-1),
                                                     global_step=epoch + 1)
                    self.tensorboard_writer.add_histogram('Grads/' + name, param.grad.data.view(-1),
                                                     global_step=epoch + 1)

        # self.proto_model.learner.load_state_dict(torch.load(model_path))
        return best_f1

    def episodic_testing(self, test_episodes):
        logger.info('---------- Proto testing starts here ----------')
        # model_path = os.path.join(self.base_path, 'saved_models', 'ProtoNet-{}.h5'.format(self.stamp))
        model_path = os.path.join(self.base_path, 'saved_models', 'Supervised-stable.h5')
        self.proto_model.learner.load_state_dict(torch.load(model_path))
        episode_accuracies, episode_precisions, episode_recalls, episode_f1s = [], [], [], []
        for episode in test_episodes:
            _, accuracy, precision, recall, f1_score, _, _ = self.proto_model([episode], updates=self.updates, testing=True)
            accuracy, precision, recall, f1_score = accuracy[0], precision[0], recall[0], f1_score[0]

            episode_accuracies.append(accuracy)
            episode_precisions.append(precision)
            episode_recalls.append(recall)
            episode_f1s.append(f1_score)

        logger.info('Avg meta-testing metrics: Accuracy = {:.5f}, precision = {:.5f}, recall = {:.5f}, '
                    'F1 score = {:.5f}'.format(np.mean(episode_accuracies),
                                               np.mean(episode_precisions),
                                               np.mean(episode_recalls),
                                               np.mean(episode_f1s)))
        return np.mean(episode_f1s)

    def testing(self, test_episodes):
        logger.info('---------- Proto testing starts here ----------')
        # model_path = os.path.join(self.base_path, 'saved_models', 'ProtoNet-{}.h5'.format(self.stamp))
#         model_path = os.path.join(self.base_path, 'saved_models', 'Supervised-stable.h5')
#         self.proto_model.learner.load_state_dict(torch.load(model_path))
        
        all_predictions, all_labels = [], []
        
        for episode in tqdm(test_episodes):
            _, _, _, _, _, predictions, labels = self.proto_model([episode], updates=self.updates, testing=True)

            all_predictions.extend(predictions)
            all_labels.extend(labels)
        
        # pdb.set_trace()
        
        accuracy, precision, recall, f1_score = utils.calculate_seqeval_metrics(all_predictions,
                                                                    all_labels, tags=episode.tags, binary=False)

        logger.info('Avg meta-testing metrics: Accuracy = {:.5f}, precision = {:.5f}, recall = {:.5f}, '
                    'F1 score = {:.5f}'.format(accuracy,
                                               precision,
                                               recall,
                                               f1_score))
        return f1_score
