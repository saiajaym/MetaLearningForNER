from datetime import datetime
from meta_learning import MetaLearning
from baseline import Baseline
from torch.utils import data

import coloredlogs
import csv
import logging
import os
import torch
torch.manual_seed(1025)

logger = logging.getLogger('AbuseLog')
coloredlogs.install(logger=logger, level='DEBUG',
                    fmt='%(asctime)s - %(name)s - %(levelname)s'
                        ' - %(message)s')

CONFIG = {
    'stamp': str(datetime.now()).replace(':', '-').replace(' ', '_'),
    'meta_model': 'abuse_meta_model',
    'learner_params': {
        'hidden_size': 128,
        'num_classes': 2,
        'embed_dim': 300,
    },
    'trained_learner': None,
    'learner_lr': 1e-1,
    'meta_lr': 1e-3,
    'num_shots': 10,
    'num_updates': 5,
    'num_test_samples': 1500,
    'num_meta_epochs': 50,
    'early_stopping': 5,
    'data_files': os.path.join(
        'data_abuse', 'dataset.{identifier}.csv'
    ),
    'embeddings': os.path.join(
        'embeddings', 'glove.840B.300d.txt'
    ),
    'base': os.path.dirname(os.path.abspath(__file__)),
}


class DataLoader(data.Dataset):
    def __init__(self, samples, classes):
        super(DataLoader, self).__init__()
        self.samples = samples
        self.classes = classes

    def __getitem__(self, index):
        return self.samples[index], self.classes[index]

    def __len__(self):
        return len(self.classes)


def tokenize_text(text):
    return text.split(' ')


def read_dataset(identifier, vocab):
    file = os.path.join(
        CONFIG['base'], CONFIG['data_files'].format(identifier=identifier)
    )
    with open(file, 'r', encoding='utf-8') as dataset:
        samples, classes = [], []
        dataset_reader = csv.reader(dataset)
        count = 0
        for line in dataset_reader:
            count += 1
            if count == 1:
                continue
            _, text, clazz = line
            classes.append(int(clazz))
            samples.append(
                [vocab.get(t, vocab['<UNK>']) for t in tokenize_text(text)]
            )
    return samples, classes


def produce_loaders(samples, classes, vocab):
    x = [[], []]
    max_len = 0
    required_samples = CONFIG['num_shots'] + CONFIG['num_test_samples']
    for sample, clazz in zip(samples, classes):
        if len(x[clazz]) == required_samples:
            continue
        x[clazz].append(sample)
        max_len = max(len(sample), max_len)
    for i in range(len(x[0])):
        while len(x[0][i]) < max_len:
            x[0][i].append(vocab['<PAD>'])
        while len(x[1][i]) < max_len:
            x[1][i].append(vocab['<PAD>'])
    support = DataLoader(
        torch.LongTensor(
            x[0][:CONFIG['num_shots']] + x[1][:CONFIG['num_shots']]
        ),
        torch.LongTensor(
            [0] * CONFIG['num_shots'] + [1] * CONFIG['num_shots']
        ),
    )
    query = DataLoader(
        torch.LongTensor(
            x[0][CONFIG['num_shots']:] + x[1][CONFIG['num_shots']:]
        ),
        torch.LongTensor(
            [0] * CONFIG['num_test_samples'] + [1] * CONFIG['num_test_samples']
        ),
    )
    support_loader = data.DataLoader(
        support, batch_size=2*CONFIG['num_shots']
    )
    query_loader = data.DataLoader(
        query, batch_size=2*CONFIG['num_test_samples']
    )
    return support_loader, query_loader


def load_vocab_and_embeddings():
    file = os.path.join(
        CONFIG['base'], CONFIG['embeddings']
    )
    embed_dim = CONFIG['learner_params']['embed_dim']
    embeds = [torch.zeros(embed_dim)]
    vocab = {'<PAD>': 0}
    with open(file, 'r', encoding='utf-8') as vectors:
        count = 0
        for vector in vectors:
            count += 1
            if count == 1:
                continue
            tokens = vector.strip().split()
            vocab[tokens[0]] = len(vocab)
            embed = [float(token) for token in tokens[-embed_dim:]]
            embeds.append(torch.Tensor(embed))
    embeds.append(torch.rand(embed_dim))
    vocab['<UNK>'] = len(vocab)
    CONFIG['embeddings'] = torch.stack(embeds)
    CONFIG['learner_params']['vocab_size'] = len(vocab)
    return vocab


if __name__ == "__main__":
    datasets = [
        'detox_attack', 'detox_toxicity', 'waseem_hovy'
    ]
    vocabulary = load_vocab_and_embeddings()

    support_loaders = []
    query_loaders = []
    for dataset in datasets:
        a, b = read_dataset(dataset, vocabulary)
        s, q = produce_loaders(a, b, vocabulary)
        support_loaders.append(s)
        query_loaders.append(q)
    logger.info('{} data loaders prepared'.format(len(datasets)))

    meta_learner = MetaLearning(CONFIG)
    meta_learner.training(support_loaders, query_loaders, datasets)
