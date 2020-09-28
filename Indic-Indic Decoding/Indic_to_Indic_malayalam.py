# Importing required libraries
import numpy as np 
import pandas as pd 
import os
import string
from string import digits
import matplotlib.pyplot as plt
import re
import ast
import copy
import seaborn as sns
from sklearn.utils import shuffle
from sklearn.model_selection import train_test_split
import keras
from keras.layers import Input, LSTM, Embedding, Dense, Bidirectional, Subtract
from keras.layers import Add, Lambda, TimeDistributed, Reshape, Activation
from keras import Sequential
from keras.optimizers import Adam
from keras.models import Model
import keras.backend as K

#!pip install keras-transformer
from keras_transformer import get_encoders
import tensorflow as tf
import tensorflow_hub as hub

pd.set_option('display.max_rows', 500)
pd.set_option('display.max_columns', 500)
pd.set_option('display.width', 1000)
pd.set_option('display.max_colwidth', -1)


!git clone https://github.com/iitmnlp/indic-swipe.git
data_orig=pd.read_excel('/content/indic-swipe/indic-to-indic-datasets/Malayalam.xlsx')
lang = 'Malayalam'
path = '/content/drive/My Drive/Indic Gesture Keyboards/'+lang

valid_chars_dict={',': 0,'<e>': 1,'D': 2,'N': 3,'അ': 4,'ആ': 5,'ഇ': 6,'ഈ': 7,'ഉ': 8,'ഊ': 9,'ഋ': 10,'ഌ': 11,'എ': 12,'ഏ': 13,
'ഐ': 14,'ഒ': 15,'ഓ': 16,'ഔ': 17,'ക': 18,'ഖ': 19,'ഗ': 20,'ഘ': 21,'ങ': 22,'ച': 23,'ഛ': 24,'ജ': 25,'ഝ': 26,'ഞ': 27,'ട': 28,
'ഠ': 29,'ഡ': 30,'ഢ': 31,'ണ': 32,'ത': 33,'ഥ': 34,'ദ': 35,'ധ': 36,'ന': 37,'ഩ': 38,'പ': 39,'ഫ': 40,'ബ': 41,'ഭ': 42,'മ': 43,'യ': 44,
'ര': 45,'റ': 46, 'ല': 47, 'ള': 48, 'ഴ': 49, 'വ': 50,'ശ': 51,'ഷ': 52,'സ': 53,'ഹ': 54,'ാ': 5,'ി': 6,'ീ': 7,'ു': 8,'ൂ': 9,'ൃ': 10,'െ': 12,'േ': 13,
 'ൈ': 14,'ൊ': 15,'ോ': 16,'ൌ': 17,'്': 55}

data_orig = pd.read_csv(path+'/gesture_embeddings.csv') 
data_orig['embedding'] = data_orig['embedding'].apply(lambda x:ast.literal_eval(x))

#@title CTC Model Setup

import keras.backend as K
import tensorflow as tf
import numpy as np

import os
from keras import Input
from keras.engine import Model
from keras.layers import Lambda
from keras.models import model_from_json
import pickle
from tensorflow.python.ops import ctc_ops as ctc

from keras.utils import Sequence, GeneratorEnqueuer, OrderedEnqueuer
import warnings
from keras.utils.generic_utils import Progbar

#from ocr_ctc.utils.utils_analysis import tf_edit_distance
#from ocr_ctc.utils.utils_keras import Kreshape_To1D
from keras.preprocessing import sequence

"""
The CTCModel class extends the Keras Model for the use of the Connectionist Temporal Classification (CTC) 
One makes use of the CTC proposed in tensorflow. Thus CTCModel can only be used with the backend tensorflow.

The CTCModel structure is composed of 3 branches. Each branch is a Keras Model:
    - One for computing the CTC loss (model_train)
    - One for predicting using the ctc_decode method (model_pred)
    - One for analyzing (model_eval) that computes the Label Error Rate (LER) and Sequence Error Rate (SER).

In a Keras Model, x is the input features and y the labels. 
Here, x data are of the form [input_sequences, label_sequences, inputs_lengths, labels_length] 
and y are not used as in a Keras Model (this is an array which is not considered,
the labeling is given in the x data structure). 
"""

def check_num_samples(ins,
                      batch_size=None,
                      steps=None,
                      steps_name='steps'):

        if steps is not None and batch_size is not None:
            raise ValueError(
                'If ' + steps_name + ' is set, the `batch_size` must be None.')

        if not ins or any(K.is_tensor(x) for x in ins):
            if steps is None:
                raise ValueError(
                    'If your data is in the form of symbolic tensors, '
                    'you should specify the `' + steps_name + '` argument '
                    '(instead of the `batch_size` argument, '
                    'because symbolic tensors are expected to produce '
                    'batches of input data).')
            return None

        if hasattr(ins[0], 'shape'):
            return int(ins[0].shape[0])
        return None  # Edge case where ins == [static_learning_phase]

class CTCModel:

    def __init__(self, inputs, outputs, greedy=True, beam_width=100, top_paths=1, charset=None): 
        """
        Initialization of a CTC Model. 
        :param inputs: Input layer of the neural network
            outputs: Last layer of the neural network before CTC (e.g. a TimeDistributed Dense)
            greedy, beam_width, top_paths: Parameters of the CTC decoding (see ctc decoding tensorflow for more details)
            charset: labels related to the input of the CTC approach
        """
        self.model_train = None
        self.model_pred = None
        self.model_eval = None
        self.inputs = inputs
        self.outputs = outputs

        self.greedy = greedy
        self.beam_width = beam_width
        self.top_paths = top_paths
        self.charset = charset


    def compile(self, optimizer):
        """
        Configures the CTC Model for training.
        
        There is 3 Keras models:
            - one for training
            - one for predicting
            - one for evaluating

        Lambda layers are used to compute:
            - the CTC loss function 
            - the CTC decoding
            - the CTC evaluation
        
        :param optimizer: The optimizer used during training
        """


        # Others inputs for the CTC approach
        labels = Input(name='labels', shape=[None])
        input_length = Input(name='input_length', shape=[1])
        label_length = Input(name='label_length', shape=[1])

        # Lambda layer for computing the loss function
        loss_out = Lambda(self.ctc_loss_lambda_func, output_shape=(1,), name='CTCloss')(
            self.outputs + [labels, input_length, label_length])

        # Lambda layer for the decoding function
        out_decoded_dense = Lambda(self.ctc_complete_decoding_lambda_func, output_shape=(None, None), name='CTCdecode', arguments={'greedy': self.greedy,
                                     'beam_width': self.beam_width, 'top_paths': self.top_paths},dtype="float32")(
            self.outputs + [input_length])

        # Lambda layer to perform an analysis (CER and SER)
        out_analysis = Lambda(self.ctc_complete_analysis_lambda_func, output_shape=(None,), name='CTCanalysis',
                                   arguments={'greedy': self.greedy,
                                              'beam_width': self.beam_width, 'top_paths': self.top_paths},dtype="float32")(
                    self.outputs + [labels, input_length, label_length])


        # create Keras models
        self.model_init = Model(inputs=self.inputs, outputs=self.outputs)
        self.model_train = Model(inputs=self.inputs + [labels, input_length, label_length], outputs=loss_out)
        self.model_pred = Model(inputs=self.inputs + [input_length], outputs=out_decoded_dense)
        self.model_eval = Model(inputs=self.inputs + [labels, input_length, label_length], outputs=out_analysis)

        # Compile models
        self.model_train.compile(loss={'CTCloss': lambda yt, yp: yp}, optimizer=optimizer)
        self.model_pred.compile(loss={'CTCdecode': lambda yt, yp: yp}, optimizer=optimizer)
        self.model_eval.compile(loss={'CTCanalysis': lambda yt, yp: yp}, optimizer=optimizer)


    def get_model_train(self):
        """
        :return: Model used for training using the CTC approach
        """
        return self.model_train

    def get_model_pred(self):
        """
        :return: Model used for testing using the CTC approach
        """
        return self.model_pred

    def get_model_eval(self):
        """
        :return: Model used for evaluating using the CTC approach
        """
        return self.model_eval

    def get_loss_on_batch(self, inputs, verbose=False):
        """
        Computation the loss
        inputs is a list of 4 elements:
            x_features, y_label, x_len, y_len (similarly to the CTC in tensorflow)
        :return: Probabilities (output of the TimeDistributedDense layer)
        """

        x = inputs[0]
        x_len = inputs[2]
        y = inputs[1]
        y_len = inputs[3]

        no_lab = True if 0 in y_len else False

        if no_lab is False:
            loss_data = self.model_train.predict_on_batch([x, y, x_len, y_len], verbose=verbose)

        loss = np.sum(loss_data) 

        return loss, loss_data


    def get_loss(self, inputs, verbose=False):
        """
        Computation the loss
        inputs is a list of 4 elements:
            x_features, y_label, x_len, y_len (similarly to the CTC in tensorflow)
        :return: Probabilities (output of the TimeDistributedDense layer)
        """

        x = inputs[0]
        x_len = inputs[2]
        y = inputs[1]
        y_len = inputs[3]
        batch_size = x.shape[0]

        no_lab = True if 0 in y_len else False

        if no_lab is False:
            loss_data = self.model_train.predict([x, y, x_len, y_len], batch_size=batch_size, verbose=verbose)

        loss = np.sum(loss_data)

        return loss, loss_data


    def get_loss_generator(self, generator, nb_batchs, verbose=False):
        """
        The generator must provide x as [input_sequences, label_sequences, inputs_lengths, labels_length]
        :return: loss on the entire dataset_manager and the loss per data
        """

        loss_per_data = []

        for k in range(nb_batchs):

            data = next(generator)

            x = data[0][0]
            x_len = data[0][2]
            y = data[0][1]
            y_len = data[0][3]
            batch_size = x.shape[0]

            no_lab = True if 0 in y_len else False

            if no_lab is False:
                loss_data = self.model_train.predict([x, y, x_len, y_len], batch_size=batch_size, verbose=verbose)
                loss_per_data += [elmt[0] for elmt in loss_data]

        loss = np.sum(loss_per_data)
        return loss, loss_per_data


    def get_probas_generator(self, generator, nb_batchs, verbose=False):
        """
        Get the probabilities of each label at each time of an observation sequence (matrix T x D)
        This is the output of the softmax function after the recurrent layers (the input of the CTC computations)
        
        Computation is done in batches using a generator. This function does not exist in a Keras Model.
        
        :return: A set of probabilities for each sequence and each time frame, one probability per label + the blank
            (this is the output of the TimeDistributed Dense layer, the blank label is the last probability)
        """

        probs_epoch = []

        for k in range(nb_batchs):

            data = next(generator)

            x = data[0][0]
            x_len = data[0][2]
            batch_size = x.shape[0]

            # Find the output of the softmax function
            probs = self.model_init.predict(x, batch_size=batch_size, verbose=verbose)

            # Select the outputs that do not refer to padding
            probs_epoch += [np.asarray(probs[data_idx, :x_len[data_idx][0], :]) for data_idx in range(batch_size)]

        return probs_epoch 

    def get_probas_on_batch(self, inputs, verbose=False):
        """
        Get the probabilities of each label at each time of an observation sequence (matrix T x D)
        This is the output of the softmax function after the recurrent layers (the input of the CTC computations)

        Computation is done for a batch. This function does not exist in a Keras Model.

        :return: A set of probabilities for each sequence and each time frame, one probability per label + the blank
            (this is the output of the TimeDistributed Dense layer, the blank label is the last probability)
        """

        x = inputs[0]
        x_len = inputs[2]
        batch_size = x.shape[0]

        #  Find the output of the softmax function
        probs = self.model_init.predict(x, batch_size=batch_size, verbose=verbose)

        # Select the outputs that do not refer to padding
        probs_epoch = [np.asarray(probs[data_idx, :x_len[data_idx][0], :]) for data_idx in range(batch_size)]

        return probs_epoch


    def get_probas(self, inputs, batch_size, verbose=False):
        """
        Get the probabilities of each label at each time of an observation sequence (matrix T x D)
        This is the output of the softmax function after the recurrent layers (the input of the CTC computations)

        Computation is done for a batch. This function does not exist in a Keras Model.

        :return: A set of probabilities for each sequence and each time frame, one probability per label + the blank
            (this is the output of the TimeDistributed Dense layer, the blank label is the last probability)
        """


        x = inputs[0]
        x_len = inputs[2]

        #  Find the output of the softmax function
        probs = self.model_init.predict(x, batch_size=batch_size, verbose=verbose)

        # Select the outputs that do not refer to padding
        probs_epoch = [np.asarray(probs[data_idx, :x_len[data_idx][0], :]) for data_idx in range(batch_size)]

        return probs_epoch



    def fit_generator(self, generator,
                      steps_per_epoch,
                      epochs=1,
                      verbose=1,
                      callbacks=None,
                      validation_data=None,
                      validation_steps=None,
                      class_weight=None,
                      max_q_size=10,
                      workers=1,
                      pickle_safe=False,
                      initial_epoch=0):
        """
        Model training on data yielded batch-by-batch by a Python generator.
        
        The generator is run in parallel to the model, for efficiency. 
        For instance, this allows you to do real-time data augmentation on images on CPU in parallel to training your model on GPU.
        
        A major modification concerns the generator that must provide x data of the form:
          [input_sequences, label_sequences, inputs_lengths, labels_length]
        (in a similar way than for using CTC in tensorflow)
        
        :param: See keras.engine.Model.fit_generator()
        :return: A History object
        """
        out = self.model_train.fit_generator(generator, steps_per_epoch, epochs=epochs, verbose=verbose,
                                             callbacks=callbacks, validation_data=validation_data,
                                             validation_steps=validation_steps, class_weight=class_weight,
                                             max_q_size=max_q_size, workers=workers, pickle_safe=pickle_safe,
                                             initial_epoch=initial_epoch)

        self.model_pred.set_weights(self.model_train.get_weights())  # required??
        self.model_eval.set_weights(self.model_train.get_weights())
        return out


    def fit(self, x=None,
            y=None,
            batch_size=None,
            epochs=1,
            verbose=1,
            callbacks=None,
            validation_split=0.0,
            validation_data=None,
            shuffle=True,
            class_weight=None,
            sample_weight=None,
            initial_epoch=0,
            steps_per_epoch=None,
            validation_steps=None):
        """
        Model training on data.

        A major modification concerns the x input of the form:
          [input_sequences, label_sequences, inputs_lengths, labels_length]
        (in a similar way than for using CTC in tensorflow)

        :param: See keras.engine.Model.fit()
        :return: A History object
        """

        out = self.model_train.fit(x=x, y=y, batch_size=batch_size, epochs=epochs, verbose=verbose,
            callbacks=callbacks, validation_split=validation_split, validation_data=validation_data,
            shuffle=shuffle, class_weight=class_weight, sample_weight=sample_weight, initial_epoch=initial_epoch,
            steps_per_epoch=steps_per_epoch, validation_steps=validation_steps)

        self.model_pred.set_weights(self.model_train.get_weights())
        self.model_eval.set_weights(self.model_train.get_weights())

        return out


    def train_on_batch(self, x, y, sample_weight=None, class_weight=None):
        """ Runs a single gradient update on a single batch of data.
        See Keras.Model for more details.
        
        
        """

        out = self.model_train.train_on_batch(x, y, sample_weight=sample_weight,
                       class_weight=class_weight)

        self.model_pred.set_weights(self.model_train.get_weights())
        self.model_eval.set_weights(self.model_train.get_weights())

        return out


    def evaluate(self, x=None, batch_size=None, verbose=1, steps=None, metrics=['loss', 'ler', 'ser']):
        """ Evaluates the model on a dataset_manager.

                :param: See keras.engine.Model.predict()
                :return: A History object

                CTC evaluation on data yielded batch-by-batch by a Python generator.

                Inputs x:
                        x_input = Input data as a 3D Tensor (batch_size, max_input_len, dim_features)
                        y = Input data as a 2D Tensor (batch_size, max_label_len)
                        x_len = 1D array with the length of each data in batch_size
                        y_len = 1D array with the length of each labeling
                        
                metrics = list of metrics that are computed. This is elements among the 3 following metrics:
                    'loss' : compute the loss function on x
                    'ler' : compute the label error rate
                    'ser' : compute the sequence error rate

                Outputs: a list containing:
                    ler_dataset = label error rate for each data (a list)
                    seq_error = sequence error rate on the dataset_manager
        """
        seq_error = 0

        x_input = x[0]
        x_len = x[2]
        y = x[1]
        y_len = x[3]
        nb_data = x_input.shape[0]

        if 'ler' in metrics or 'ser' in metrics:
            eval_batch = self.model_eval.predict([x_input, y, x_len, y_len], batch_size=batch_size, verbose=verbose, steps=steps)

        if 'ser' in metrics:
            seq_error += np.sum([1 for ler_data in eval_batch if ler_data != 0])
            seq_error = seq_error / nb_data if nb_data > 0 else -1.

        outmetrics = []
        if 'loss' in metrics:
            outmetrics.append(self.get_loss(x))
        if 'ler' in metrics:
            outmetrics.append(eval_batch)
        if 'ser' in metrics:
            outmetrics.append(seq_error)

        return outmetrics

    def test_on_batch(self, x=None, metrics=['loss', 'ler', 'ser']):
        """ Name of a Keras Model function: this relates to evaluate on batch """
        return self.evaluate_on_batch(x)


    def evaluate_on_batch(self, x=None, metrics=['loss', 'ler', 'ser']):
        """ Evaluates the model on a dataset_manager.

                :param: See keras.engine.Model.predict_on_batch()
                :return: A History object

                CTC evaluation on data yielded batch-by-batch by a Python generator.

                Inputs x:
                        x_input = Input data as a 3D Tensor (batch_size, max_input_len, dim_features)
                        y = Input data as a 2D Tensor (batch_size, max_label_len)
                        x_len = 1D array with the length of each data in batch_size
                        y_len = 1D array with the length of each labeling
                        
                metrics = list of metrics that are computed. This is elements among the 3 following metrics:
                    'loss' : compute the loss function on x
                    'ler' : compute the label error rate
                    'ser' : compute the sequence error rate

                Outputs: a list containing:
                    ler_dataset = label error rate for each data (a list)
                    seq_error = sequence error rate on the dataset_manager
        """
        seq_error = 0

        x_input = x[0]
        x_len = x[2]
        y = x[1]
        y_len = x[3]
        nb_data = x_input.shape[0]

        if 'ler' in metrics or 'ser' in metrics:
            eval_batch = self.model_eval.predict_on_batch([x_input, y, x_len, y_len])

        if 'ser' in metrics:
            seq_error += np.sum([1 for ler_data in eval_batch if ler_data != 0])
            seq_error = seq_error / nb_data if nb_data > 0 else -1.

        outmetrics = []
        if 'loss' in metrics:
            outmetrics.append(self.get_loss(x))
        if 'ler' in metrics:
            outmetrics.append(eval_batch)
        if 'ser' in metrics:
            outmetrics.append(seq_error)

        return outmetrics


    def evaluate_generator(self, generator, steps=None, max_queue_size=10, workers=1, use_multiprocessing=False, verbose=0, metrics=['ler', 'ser']):
        """ Evaluates the model on a data generator.
        
        :param: See keras.engine.Model.fit()
        :return: A History object
        
        CTC evaluation on data yielded batch-by-batch by a Python generator.

        Inputs:
            generator = DataGenerator class that returns:
                    x = Input data as a 3D Tensor (batch_size, max_input_len, dim_features)
                    y = Input data as a 2D Tensor (batch_size, max_label_len)
                    x_len = 1D array with the length of each data in batch_size
                    y_len = 1D array with the length of each labeling
            nb_batchs = number of batchs that are evaluated
            
            metrics = list of metrics that are computed. This is elements among the 3 following metrics:
                    'loss' : compute the loss function on x
                    'ler' : compute the label error rate
                    'ser' : compute the sequence error rate
            Warning: if the 'loss' and another metric are requested, make sure that the number of steps allows to evaluate the entire dataset,
                   even if the data given by the generator will be not the same for all metrics. To make sure, you can only compute 'ler' and 'ser' here
                   then initialize again the generator and call get_loss_generator. 
            
        

        Outputs: a list containing the metrics given in argument:
            loss : the loss on the set
            ler : the label error rate for each data (a list)
            seq_error : the sequence error rate on the dataset
                 """

        if 'ler' in metrics or 'ser' in metrics:
            ler_dataset = self.model_eval.predict_generator(generator, steps,
                          max_queue_size=max_queue_size,
                          workers=workers,
                          use_multiprocessing=use_multiprocessing,
                          verbose=verbose)
        if 'ser' in metrics:
            seq_error = float(np.sum([1 for ler_data in ler_dataset if ler_data != 0])) / len(ler_dataset) if len(ler_dataset)>0 else 1.

        outmetrics = []
        if 'loss' in metrics:
            outmetrics.append(self.get_loss_generator(generator, steps))
        if 'ler' in metrics:
            outmetrics.append(ler_dataset)
        if 'ser' in metrics:
            outmetrics.append(seq_error)

        return outmetrics


    def predict_on_batch(self, x):
        """Returns predictions for a single batch of samples.

                # Arguments
                    x: [Input samples as a Numpy array, Input length as a numpy array]

                # Returns
                    Numpy array(s) of predictions.
        """
        batch_size = x[0].shape[0]

        return self.predict(x, batch_size=batch_size)


    def predict_generator(self, generator, steps,
                          max_queue_size=10,
                          workers=1,
                          use_multiprocessing=False,
                          verbose=0,
                          decode_func=None):
        """Generates predictions for the input samples from a data generator.

        The generator should return the same kind of data as accepted by
        `predict_on_batch`.
        
        generator = DataGenerator class that returns:
                        x = Input data as a 3D Tensor (batch_size, max_input_len, dim_features)
                        y = Input data as a 2D Tensor (batch_size, max_label_len)
                        x_len = 1D array with the length of each data in batch_size
                        y_len = 1D array with the length of each labeling

        # Arguments
            generator: Generator yielding batches of input samples
                    or an instance of Sequence (keras.utils.Sequence)
                    object in order to avoid duplicate data
                    when using multiprocessing.
            steps: Total number of steps (batches of samples)
                to yield from `generator` before stopping.
            max_queue_size: Maximum size for the generator queue.
            workers: Maximum number of processes to spin up
                when using process based threading
            use_multiprocessing: If `True`, use process based threading.
                Note that because
                this implementation relies on multiprocessing,
                you should not pass
                non picklable arguments to the generator
                as they can't be passed
                easily to children processes.
            verbose: verbosity mode, 0 or 1.
            decode_func: a function for decoding a list of predicted sequences (using self.charset)

        # Returns
            A tuple containing:
                A numpy array(s) of predictions.
                A numpy array(s) of ground truth.

        # Raises
            ValueError: In case the generator yields
                data in an invalid format.
        """
        self.model_pred._make_predict_function()

        steps_done = 0
        wait_time = 0.01
        all_outs = []
        all_lab = []
        is_sequence = isinstance(generator, Sequence)
        if not is_sequence and use_multiprocessing and workers > 1:
            warnings.warn(
                UserWarning('Using a generator with `use_multiprocessing=True`'
                            ' and multiple workers may duplicate your data.'
                            ' Please consider using the`keras.utils.Sequence'
                            ' class.'))
        enqueuer = None

        try:
            if is_sequence:
                enqueuer = OrderedEnqueuer(generator,
                                           use_multiprocessing=use_multiprocessing)
            else:
                enqueuer = GeneratorEnqueuer(generator,
                                             use_multiprocessing=use_multiprocessing,
                                             wait_time=wait_time)
            enqueuer.start(workers=workers, max_queue_size=max_queue_size)
            output_generator = enqueuer.get()

            if verbose == 1:
                progbar = Progbar(target=steps)

            while steps_done < steps:
                generator_output = next(output_generator)
                if isinstance(generator_output, tuple):
                    # Compatibility with the generators
                    # used for training.
                    if len(generator_output) == 2:
                        x, _ = generator_output
                    elif len(generator_output) == 3:
                        x, _, _ = generator_output
                    else:
                        raise ValueError('Output of generator should be '
                                         'a tuple `(x, y, sample_weight)` '
                                         'or `(x, y)`. Found: ' +
                                         str(generator_output))
                else:
                    # Assumes a generator that only
                    # yields inputs (not targets and sample weights).
                    x = generator_output

                [x_input, y, x_length, y_length] = x
                outs = self.predict_on_batch([x_input, x_length])
                if not isinstance(outs, list):
                    outs = [outs]

                if not all_outs:
                    for out in outs:
                        all_outs.append([])
                        all_lab.append([])

                for i, out in enumerate(outs):
                    all_outs[i].append([val_out for val_out in out if val_out!=-1])
                    if isinstance(y_length[i], list):
                        all_lab[i].append(y[i][:y_length[i][0]])
                    elif isinstance(y_length[i], int):
                        all_lab[i].append(y[i][:y_length[i]])
                    elif isinstance(y_length[i], float):
                        all_lab[i].append(y[i][:int(y_length[i])])
                    else:
                        all_lab[i].append(y[i])

                steps_done += 1
                if verbose == 1:
                    progbar.update(steps_done)

        finally:
            if enqueuer is not None:
                enqueuer.stop()

        batch_size = len(all_outs)
        nb_data = len(all_outs[0])
        pred_out = []
        lab_out = []
        for i in range(nb_data):
            pred_out += [all_outs[b][i] for b in range(batch_size)]
            lab_out +=  [all_lab[b][i] for b in range(batch_size)]

        if decode_func is not None:  # convert model prediction (a label between 0 to nb_labels to an original label sequence)
            pred_out = decode_func(pred_out, self.charset)
            lab_out = decode_func(lab_out, self.charset)

        return pred_out, lab_out


    def predict(self, x, batch_size=None, verbose=0, steps=None, max_len=None, max_value=999):

        """
        The same function as in the Keras Model but with a different function predict_loop for dealing with variable length predictions
        Except that x = [x_features, x_len]
        
        Generates output predictions for the input samples.

                Computation is done in batches.

                # Arguments
                    x: The input data, as a Numpy array
                        (or list of Numpy arrays if the model has multiple outputs).
                    batch_size: Integer. If unspecified, it will default to 32.
                    verbose: Verbosity mode, 0 or 1.
                    steps: Total number of steps (batches of samples)
                        before declaring the prediction round finished.
                        Ignored with the default value of `None`.

                # Returns
                    Numpy array(s) of predictions.

                # Raises
                    ValueError: In case of mismatch between the provided
                        input data and the model's expectations,
                        or in case a stateful model receives a number of samples
                        that is not a multiple of the batch size.
                """
        [x_inputs, x_len] = x
        if max_len is None:
            max_len = np.max(x_len)

        # Backwards compatibility.
        if batch_size is None and steps is None:
            batch_size = 32
        if x is None and steps is None:
            raise ValueError('If predicting from data tensors, '
                             'you should specify the `steps` '
                             'argument.')
        # Validate user data.
        x = _standardize_input_data(x, self.model_pred._feed_input_names,
                                    self.model_pred._feed_input_shapes,
                                    check_batch_axis=False)
        if self.model_pred.stateful:
            if x[0].shape[0] > batch_size and x[0].shape[0] % batch_size != 0:
                raise ValueError('In a stateful network, '
                                 'you should only pass inputs with '
                                 'a number of samples that can be '
                                 'divided by the batch size. Found: ' +
                                 str(x[0].shape[0]) + ' samples. '
                                                      'Batch size: ' + str(batch_size) + '.')

        # Prepare inputs, delegate logic to `_predict_loop`.
        if self.model_pred.uses_learning_phase and not isinstance(K.learning_phase(), int):
            ins = x + [0.]
        else:
            ins = x
        self.model_pred._make_predict_function()
        f = self.model_pred.predict_function
        out = self._predict_loop(f, ins, batch_size=batch_size, max_value=max_value,
                                  verbose=verbose, steps=steps, max_len=max_len)

        out_decode = [dec_data[:list(dec_data).index(max_value)] if max_value in dec_data else dec_data for i,dec_data in enumerate(out)]
        return out_decode

    

    def _predict_loop(self, f, ins, max_len=100, max_value=999, batch_size=32, verbose=0, steps=None):
        """Abstract method to loop over some data in batches.

        Keras function that has been modified. 
        
        # Arguments
            f: Keras function returning a list of tensors.
            ins: list of tensors to be fed to `f`.
            batch_size: integer batch size.
            verbose: verbosity mode.
            steps: Total number of steps (batches of samples)
                before declaring `_predict_loop` finished.
                Ignored with the default value of `None`.

        # Returns
            Array of predictions (if the model has a single output)
            or list of arrays of predictions
            (if the model has multiple outputs).
        """
        num_samples = check_num_samples(ins,
                                    batch_size=batch_size,
                                    steps=steps,
                                    steps_name='steps')

        #self.model_pred._check_num_samples(ins, batch_size,steps, 'steps')

        if steps is not None:
            # Step-based predictions.
            # Since we do not know how many samples
            # we will see, we cannot pre-allocate
            # the returned Numpy arrays.
            # Instead, we store one array per batch seen
            # and concatenate them upon returning.
            unconcatenated_outs = []
            for step in range(steps):
                batch_outs = f(ins)
                if not isinstance(batch_outs, list):
                    batch_outs = [batch_outs]
                if step == 0:
                    for batch_out in batch_outs:
                        unconcatenated_outs.append([])
                for i, batch_out in enumerate(batch_outs):
                    unconcatenated_outs[i].append(batch_out)

            if len(unconcatenated_outs) == 1:
                return np.concatenate(unconcatenated_outs[0], axis=0)
            return [np.concatenate(unconcatenated_outs[i], axis=0)
                    for i in range(len(unconcatenated_outs))]
        else:
            # Sample-based predictions.
            outs = []
            batches = _make_batches(num_samples, batch_size)
            index_array = np.arange(num_samples)
            for batch_index, (batch_start, batch_end) in enumerate(batches):
                batch_ids = index_array[batch_start:batch_end]
                if ins and isinstance(ins[-1], float):
                    # Do not slice the training phase flag.
                    ins_batch = _slice_arrays(ins[:-1], batch_ids) + [ins[-1]]
                else:
                    ins_batch = _slice_arrays(ins, batch_ids)
                batch_outs = f(ins_batch)
                if not isinstance(batch_outs, list):
                    batch_outs = [batch_outs]
                if batch_index == 0:
                    # Pre-allocate the results arrays.
                    for batch_out in batch_outs:
                        shape = (num_samples,max_len)
                        outs.append(np.zeros(shape, dtype=batch_out.dtype))
                for i, batch_out in enumerate(batch_outs):
                    outs[i][batch_start:batch_end] = sequence.pad_sequences(batch_out, value=float(max_value), maxlen=max_len,
                                     dtype=batch_out.dtype, padding="post")

            if len(outs) == 1:
                return outs[0]
            return outs


    @staticmethod
    def ctc_loss_lambda_func(args):
        """
        Function for computing the ctc loss (can be put in a Lambda layer)
        :param args: 
            y_pred, labels, input_length, label_length
        :return: CTC loss 
        """

        y_pred, labels, input_length, label_length = args
        return K.ctc_batch_cost(labels, y_pred, input_length, label_length)#, ignore_longer_outputs_than_inputs=True)


    @staticmethod
    def ctc_complete_decoding_lambda_func(args, **arguments):
        """
        Complete CTC decoding using Keras (function K.ctc_decode)
        :param args: 
            y_pred, input_length
        :param arguments:
            greedy, beam_width, top_paths
        :return: 
            K.ctc_decode with dtype='float32'
        """

        #import tensorflow as tf # Require for loading a model saved

        y_pred, input_length = args
        print(input_length)
        my_params = arguments

        assert (K.backend() == 'tensorflow')

        return K.cast(K.ctc_decode(y_pred, tf.squeeze(input_length), greedy=my_params['greedy'], beam_width=my_params['beam_width'], top_paths=my_params['top_paths'])[0][0], dtype='float32')

    @staticmethod
    def ctc_complete_analysis_lambda_func(args, **arguments):
        """
        Complete CTC analysis using Keras and tensorflow
        WARNING : tf is required 
        :param args: 
            y_pred, labels, input_length, label_len
        :param arguments:
            greedy, beam_width, top_paths
        :return: 
            ler = label error rate
        """

        #import tensorflow as tf # Require for loading a model saved

        y_pred, labels, input_length, label_len = args
        my_params = arguments

        assert (K.backend() == 'tensorflow')

        batch = tf.log(tf.transpose(y_pred, perm=[1, 0, 2]) + 1e-8)
        input_length = tf.to_int32(tf.squeeze(input_length))
        print(input_length)
        #22424234233242
        greedy = my_params['greedy']
        beam_width = my_params['beam_width']
        top_paths = my_params['top_paths']
        print(input_length.dtype)
        if greedy:
            print(input_length)
            (decoded, log_prob) = ctc.ctc_greedy_decoder(
                inputs=batch,
                sequence_length=input_length[0])
            
        else:
            print(input_length) 
            (decoded, log_prob) = ctc.ctc_beam_search_decoder(
                inputs=batch, sequence_length=input_length,
                beam_width=beam_width, top_paths=top_paths)

        cast_decoded = tf.cast(decoded[0], tf.float32)

        sparse_y = K.ctc_label_dense_to_sparse(labels, tf.cast(tf.squeeze(label_len), tf.int32))
        ed_tensor = tf_edit_distance(cast_decoded, sparse_y, norm=True)
        ler_per_seq = Kreshape_To1D(ed_tensor)

        return K.cast(ler_per_seq, dtype='float32')



    def save_model(self, path_dir, charset=None):
        """ Save a model in path_dir 
        save model_train, model_pred and model_eval in json 
        save inputs and outputs in json
        save model CTC parameters in a pickle 
        
        :param path_dir: directory where the model architecture will be saved
        :param charset: set of labels (useful to keep the label order)
        """

        model_json = self.model_train.to_json()
        with open(path_dir + "/model_train.json", "w") as json_file:
            json_file.write(model_json)

        model_json = self.model_pred.to_json()
        with open(path_dir + "/model_pred.json", "w") as json_file:
            json_file.write(model_json)

        model_json = self.model_eval.to_json()
        with open(path_dir + "/model_eval.json", "w") as json_file:
            json_file.write(model_json)

        model_json = self.model_init.to_json()
        with open(path_dir + "/model_init.json", "w") as json_file:
            json_file.write(model_json)

        param = {'greedy': self.greedy, 'beam_width': self.beam_width, 'top_paths': self.top_paths, 'charset': self.charset}

        output = open(path_dir + "/model_param.pkl", 'wb')
        p = pickle.Pickler(output)
        p.dump(param)
        output.close()


    def load_model(self, path_dir, optimizer, file_weights=None):
        """ Load a model in path_dir 
        load model_train, model_pred and model_eval from json 
        load inputs and outputs from json
        load model CTC parameters from a pickle 
        
        :param path_dir: directory where the model is saved
        :param optimizer: The optimizer used during training
        """


        json_file = open(path_dir + '/model_train.json', 'r')
        loaded_model_json = json_file.read()
        json_file.close()
        self.model_train = model_from_json(loaded_model_json)

        json_file = open(path_dir + '/model_pred.json', 'r')
        loaded_model_json = json_file.read()
        json_file.close()
        self.model_pred = model_from_json(loaded_model_json, custom_objects={"tf": tf})

        json_file = open(path_dir + '/model_eval.json', 'r')
        loaded_model_json = json_file.read()
        json_file.close()
        self.model_eval = model_from_json(loaded_model_json, custom_objects={"tf": tf, "ctc": ctc,
                                                                             "tf_edit_distance": tf_edit_distance,
                                                                             "Kreshape_To1D": Kreshape_To1D})

        json_file = open(path_dir + '/model_init.json', 'r')
        loaded_model_json = json_file.read()
        json_file.close()
        self.model_init = model_from_json(loaded_model_json, custom_objects={"tf": tf})

        self.inputs = self.model_init.inputs
        self.outputs = self.model_init.outputs

        input = open(path_dir + "/model_param.pkl", 'rb')
        p = pickle.Unpickler(input)
        param = p.load()
        input.close()

        self.greedy = param['greedy'] if 'greedy' in param.keys() else self.greedy
        self.beam_width = param['beam_width'] if 'beam_width' in param.keys() else self.beam_width
        self.top_paths = param['top_paths'] if 'top_paths' in param.keys() else self.top_paths
        self.charset = param['charset'] if 'charset' in param.keys() else self.charset

        self.compile(optimizer)

        if file_weights is not None:
            if os.path.exists(file_weights):
                self.model_train.load_weights(file_weights)
                self.model_pred.set_weights(self.model_train.get_weights())
                self.model_eval.set_weights(self.model_train.get_weights())
            elif os.path.exists(path_dir + file_weights):
                self.model_train.load_weights(path_dir + file_weights)
                self.model_pred.set_weights(self.model_train.get_weights())
                self.model_eval.set_weights(self.model_train.get_weights())



def _standardize_input_data(data, names, shapes=None,
                            check_batch_axis=True,
                            exception_prefix=''):
    """Normalizes inputs and targets provided by users.

    Users may pass data as a list of arrays, dictionary of arrays,
    or as a single array. We normalize this to an ordered list of
    arrays (same order as `names`), while checking that the provided
    arrays have shapes that match the network's expectations.

    # Arguments
        data: User-provided input data (polymorphic).
        names: List of expected array names.
        shapes: Optional list of expected array shapes.
        check_batch_axis: Boolean; whether to check that
            the batch axis of the arrays matches the expected
            value found in `shapes`.
        exception_prefix: String prefix used for exception formatting.

    Keras function that has been modified. 
    
    # Returns
        List of standardized input arrays (one array per model input).

    # Raises
        ValueError: in case of improperly formatted user-provided data.
    """
    if not names:
        if data is not None and hasattr(data, '__len__') and len(data):
            raise ValueError('Error when checking model ' +
                             exception_prefix + ': '
                             'expected no data, but got:', data)
        return []
    if data is None:
        return [None for _ in range(len(names))]
    if isinstance(data, dict):
        arrays = []
        for name in names:
            if name not in data:
                raise ValueError('No data provided for "' +
                                 name + '". Need data for each key in: ' +
                                 str(names))
            arrays.append(data[name])
    elif isinstance(data, list):
        if len(data) != len(names):
            if data and hasattr(data[0], 'shape'):
                raise ValueError('Error when checking model ' +
                                 exception_prefix +
                                 ': the list of Numpy arrays '
                                 'that you are passing to your model '
                                 'is not the size the model expected. '
                                 'Expected to see ' + str(len(names)) +
                                 ' array(s), but instead got '
                                 'the following list of ' + str(len(data)) +
                                 ' arrays: ' + str(data)[:200] +
                                 '...')
            else:
                if len(names) == 1:
                    data = [np.asarray(data)]
                else:
                    raise ValueError(
                        'Error when checking model ' +
                        exception_prefix +
                        ': you are passing a list as '
                        'input to your model, '
                        'but the model expects '
                        'a list of ' + str(len(names)) +
                        ' Numpy arrays instead. '
                        'The list you passed was: ' +
                        str(data)[:200])
        arrays = data
    else:
        if not hasattr(data, 'shape'):
            raise TypeError('Error when checking model ' +
                            exception_prefix +
                            ': data should be a Numpy array, '
                            'or list/dict of Numpy arrays. '
                            'Found: ' + str(data)[:200] + '...')
        if len(names) > 1:
            # Case: model expects multiple inputs but only received
            # a single Numpy array.
            raise ValueError('The model expects ' + str(len(names)) + ' ' +
                             exception_prefix +
                             ' arrays, but only received one array. '
                             'Found: array with shape ' + str(data.shape))
        arrays = [data]

    # Make arrays at least 2D.
    for i in range(len(names)):
        array = arrays[i]
        if len(array.shape) == 1:
            array = np.expand_dims(array, 1)
            arrays[i] = array

    # Check shapes compatibility.
    if shapes:
        for i in range(len(names)):
            if shapes[i] is None:
                continue
            array = arrays[i]
            if len(array.shape) != len(shapes[i]):
                raise ValueError('Error when checking ' + exception_prefix +
                                 ': expected ' + names[i] +
                                 ' to have ' + str(len(shapes[i])) +
                                 ' dimensions, but got array with shape ' +
                                 str(array.shape))
            for j, (dim, ref_dim) in enumerate(zip(array.shape, shapes[i])):
                if not j and not check_batch_axis:
                    # skip the first axis
                    continue
                if ref_dim:
                    if ref_dim != dim:
                        raise ValueError(
                            'Error when checking ' + exception_prefix +
                            ': expected ' + names[i] +
                            ' to have shape ' + str(shapes[i]) +
                            ' but got array with shape ' +
                            str(array.shape))
    return arrays


def _slice_arrays(arrays, start=None, stop=None):
    """Slice an array or list of arrays.

    This takes an array-like, or a list of
    array-likes, and outputs:
        - arrays[start:stop] if `arrays` is an array-like
        - [x[start:stop] for x in arrays] if `arrays` is a list

    Can also work on list/array of indices: `_slice_arrays(x, indices)`

    Keras function that has been modified. 
    
    # Arguments
        arrays: Single array or list of arrays.
        start: can be an integer index (start index)
            or a list/array of indices
        stop: integer (stop index); should be None if
            `start` was a list.

    # Returns
        A slice of the array(s).
    """
    if arrays is None:
        return [None]
    elif isinstance(arrays, list):
        if hasattr(start, '__len__'):
            # hdf5 datasets only support list objects as indices
            if hasattr(start, 'shape'):
                start = start.tolist()
            return [None if x is None else x[start] for x in arrays]
        else:
            return [None if x is None else x[start:stop] for x in arrays]
    else:
        if hasattr(start, '__len__'):
            if hasattr(start, 'shape'):
                start = start.tolist()
            return arrays[start]
        elif hasattr(start, '__getitem__'):
            return arrays[start:stop]
        else:
            return [None]


def _make_batches(size, batch_size):
    """Returns a list of batch indices (tuples of indices).

    Keras function that has been modified. 
    
    # Arguments
        size: Integer, total size of the data to slice into batches.
        batch_size: Integer, batch size.

    # Returns
        A list of tuples of array indices.
    """
    num_batches = int(np.ceil(size / float(batch_size)))
    return [(i * batch_size, min(size, (i + 1) * batch_size))
            for i in range(0, num_batches)]


def Kreshape_To1D(my_tensor):
    """ Reshape to a 1D Tensor using K.reshape"""

    sum_shape = K.sum(K.shape(my_tensor))
    return K.reshape(my_tensor, (sum_shape,))


def tf_edit_distance(hypothesis, truth, norm=False):
    """ Edit distance using tensorflow 

    inputs are tf.Sparse_tensors """

    return tf.edit_distance(hypothesis, truth, normalize=norm, name='edit_distance')

# Maps matras to corresponding indices (but not vowels) along with consonants
idx_to_dict = {}
for i in valid_chars_dict:
    idx_to_dict[valid_chars_dict[i]] = i

# Maps vowels to corresponding indices (but not matras) along with consonants
idx_to_dict_2 = {}
for i in valid_chars_dict:
    if not valid_chars_dict[i] in idx_to_dict_2:
        idx_to_dict_2[valid_chars_dict[i]] = i

num_characters_on_keyboard = 55

def make_one_hot(selected_idx, num_characters_on_keyboard):
    li = [0]*num_characters_on_keyboard
    li[selected_idx] = 1
    return li

LATENT_DIM = 256
MAX_SEQUENCE_LENGTH = 100
EMBEDDING_DIM = 1024
MAX_SPAN_LENGTH = 200 # Decide based on maximum value of maxlen column
MAX_TARGET_LENGTH = 21 # Decide based on maximum value of maxlen_word column

data_orig['maxlen']=data_orig['embedding'].apply(lambda x:len(x)) 
data_orig = data_orig[data_orig['maxlen']<=MAX_SPAN_LENGTH-5] # +5 is only to a have a few <e>'s at the end of all sequences
#print(np.max(np.array(data_orig['maxlen'].tolist())))

def modify_list(li):
    for sub_li in li:
        append_list=make_one_hot(sub_li[-1],num_characters_on_keyboard)
        sub_li.extend(append_list)
    return li

data_orig['full_embed'] = data_orig['embedding'].apply(lambda x:modify_list(x))

input_texts = copy.deepcopy(data_orig['full_embed'].tolist())
target_texts = copy.deepcopy(data_orig['word'].tolist()) 
target_texts_word = copy.deepcopy(data_orig['word'].tolist())

pad_point = [0]*(5+num_characters_on_keyboard)

TRAIN_SIZE = int(0.6*len(input_texts))
#print("TRAIN_SIZE = ", TRAIN_SIZE)

# Make list corresponding to all words of same length
input_texts_len = []
for i in range(len(input_texts)):
    input_texts_len.append(len(input_texts[i]))
    input_texts[i].extend([pad_point]*(MAX_SPAN_LENGTH-len(input_texts[i])))

# Convert target words into list of indices based on valid_chars_dict
target_pad_value  = '<e>'
target_texts_len = []
for i in range(len(target_texts)):
    target_texts[i] = target_texts[i].split()
    target_texts_len.append(len(target_texts[i]))
    target_texts[i].extend([target_pad_value]*(MAX_TARGET_LENGTH-len(target_texts[i]))) 
    for j in range(len(target_texts[i])):
        target_texts[i][j] = valid_chars_dict[target_texts[i][j]]

# If length of input path is less than length of target word, CTC cannot process it. Hence, remove such cases
input_texts_len.append(-1)
i=0
while (input_texts_len[i]!=-1):
    if(input_texts_len[i]<=target_texts_len[i]):
        del input_texts[i], target_texts[i], input_texts_len[i], target_texts_len[i], target_texts_word[i]
        i=i-1
    i=i+1
del input_texts_len[-1]

# Convert into numpy arrays
input_texts = np.array(input_texts)
target_texts = np.array(target_texts)
input_texts_len = np.array(input_texts_len)
target_texts_len = np.array(target_texts_len)

# Normalize input_texts
max_list = [np.max(input_texts[:,:,i]) for i in range(5)]
min_list = [np.min(input_texts[:,:,i]) for i in range(5)]

for i in range(len(input_texts)):
    for j in range(len(input_texts[i])):
        for k in range(5):
            input_texts[i][j][k] = 2*(input_texts[i][j][k]-min_list[k])/(max_list[k]-min_list[k]) - 1

#Build the CTC model for path decoding

def create_network():
    encoder_input = Input(shape=(MAX_SPAN_LENGTH, num_characters_on_keyboard+5), name='Encoder_input')
    encoded_layer = get_encoders(
            encoder_num=1,
            input_layer=encoder_input,
            head_num=5,
            hidden_dim=128,
            attention_activation='relu',
            feed_forward_activation='relu',
            dropout_rate=0.05
    )
    dense = TimeDistributed(Dense(num_characters_on_keyboard+10, name="dense"))(encoded_layer) 
    outrnn = Activation('softmax',name='softmax')(dense)
    network = CTCModel([encoder_input], [outrnn])
    network.compile(Adam(lr=0.01))
    return network

network = create_network()



# # FOR TRAINING
network.fit(x=[input_texts[:TRAIN_SIZE], target_texts[:TRAIN_SIZE],input_texts_len[:TRAIN_SIZE],target_texts_len[:TRAIN_SIZE]], 
            y=np.zeros(TRAIN_SIZE), batch_size=256, epochs=23) 

network.model_train.save_weights(path+'/transformer_ctc_weights_stored.h5')

# Predict using greedy decoding
pred = network.predict([input_texts[TRAIN_SIZE:], input_texts_len[TRAIN_SIZE:]], batch_size=256)#, max_value=0)

idx=1000
corr_pred = 0
wrong_pred_list = []
for i in range(len(pred)):
    for j in range(len(pred[i])):
        if(pred[i][j]==-1):
            idx = j
            break
        idx = len(pred[i]) # If -1 does not occur in the prediction
    if (np.all(pred[i][:idx]==target_texts[TRAIN_SIZE+i][:idx])==True):
        corr_pred+=1
    else:
        wrong_pred_list.append(i)
print("Accuracy of path decoder using greedy decoding = ", str(corr_pred/len(pred)))

# Converting predicted sequences into corresponding words
word_pred = []
for i in range(len(pred)):
    next_word = []
    for j in range(len(pred[i])):
        if pred[i][j]==-1:
            break
        elif len(next_word)==0:
            next_word.append(idx_to_dict_2[int(pred[i][j])]) # Use full vowel, not matra for 1st position
        else:
            next_word.append(idx_to_dict[int(pred[i][j])]) # Use matra, not full vowel for later positions
    word_pred.append(' '.join(next_word))

"""### Spelling Correction"""

pred_list_sep = word_pred # List of predicted words (characters should be separated by ' ')
corr_list_sep = target_texts_word[TRAIN_SIZE:] # Vocabulary words

# Setting up ELMo
def elmo_vectors(x):
    embeddings = elmo(x, signature="default", as_dict=True)["elmo"]
    with tf.Session() as sess:
        sess.run(tf.global_variables_initializer())
        sess.run(tf.tables_initializer())
        # return average of ELMo features
        return sess.run(embeddings)

elmo = hub.Module("https://tfhub.dev/google/elmo/2", trainable=True)
tf.logging.set_verbosity(tf.logging.ERROR)

# Get set of unique words to form a vocabulary
corr_list_sep_unique = list(set(corr_list_sep))
corr_list_dict = {k: v for v, k in enumerate(corr_list_sep_unique)}

# To prevent Resource Exhaust error, the array of words is split into parts and ELMo vectors are generated for each part separately
def split_elmo_task(x, elmo_split):
    len_computed = 0
    elmo_res = np.sum(elmo_vectors(x[:min(elmo_split,len(x))]), axis=1)
    len_computed = min(elmo_split,len(x))
    print(len_computed) 
    while(len_computed<len(x)):
        elmo_temp = np.sum(elmo_vectors(x[len_computed:min(len_computed+elmo_split, len(x))]), axis=1)
        elmo_res = np.concatenate([elmo_res, elmo_temp], axis=0) 
        len_computed+=min(len_computed+elmo_split, len(x))-len_computed 
        print(len_computed)
    return elmo_res

print("No. of words in dev+test set = ", len(pred_list_sep))
print("No. of words in vocabulary before filtering= ", len(corr_list_sep))
print("No. of unique words in vocabulary = ", len(corr_list_sep_unique))

# Generation of ELMo vectors
corr_elmo = split_elmo_task(corr_list_sep_unique,800) 
pred_elmo = split_elmo_task(pred_list_sep, 800)

# Normalize the ELMo vectors
pred_elmo_2 = (pred_elmo-np.min(pred_elmo))/(np.max(pred_elmo)-np.min(pred_elmo)) 
corr_elmo_2 = (corr_elmo-np.min(corr_elmo))/(np.max(corr_elmo)-np.min(corr_elmo)) 
# For releasing storage space
del pred_elmo, corr_elmo

# Specify part of pred_list_sep should be used for training. Rest will be used for testing
TRAIN_SPLIT = int(0.5*len(word_pred))

# Language Model for training with dense layer
pred_placeholder = Input(shape=(1024,)) 
corr_placeholder = Input(shape=(len(corr_list_sep_unique), 1024))
#print(pred_placeholder.shape, corr_placeholder.shape)
sub = Subtract()([corr_placeholder, pred_placeholder])
#print(sub.shape)
squared = Lambda(lambda x:-x**2)(sub)
#print(squared.shape) 
td_layer_1 = TimeDistributed(Dense(64))
td = td_layer_1(squared)  
td_layer_2 = TimeDistributed(Dense(1))
td = td_layer_2(td)  
#print(td.shape)
act_1 = Reshape((len(corr_list_sep_unique),))(td)
act_1 = Activation('softmax')(act_1) 
#print(act_1.shape)

comp_model = Model([pred_placeholder, corr_placeholder],act_1)   
comp_model.compile(metrics=['accuracy'], loss='sparse_categorical_crossentropy', optimizer=Adam(lr=0.05))  #0.1 
corr_repeated_2 = np.broadcast_to(corr_elmo_2, (len(pred_elmo_2[:TRAIN_SPLIT]), corr_elmo_2.shape[0], corr_elmo_2.shape[1]))  

class_array = np.zeros((len(pred_elmo_2[:TRAIN_SPLIT]), 1)) 
for i in range(len(pred_elmo_2[:TRAIN_SPLIT])): 
    class_array[i] = corr_list_dict[corr_list_sep[i]]

# Load weights of language model (with 2 dense layers) 
comp_model.load_weights(path+'/comp_model_elmo_weights.h5')

corr_repeated_2 = np.broadcast_to(corr_elmo_2, (len(pred_elmo_2[TRAIN_SPLIT:]), corr_elmo_2.shape[0], corr_elmo_2.shape[1]))   
final_preds = comp_model.predict([pred_elmo_2[TRAIN_SPLIT:], corr_repeated_2])

# Get overall accuracy after the spell check model
crr=0  # No. of correct predictions
for i in range(0, len(final_preds)):
    if corr_list_dict[corr_list_sep[(TRAIN_SPLIT+i)]] == np.argmax(final_preds[i]):
        crr+=1
print("Accuracy following language model = {}%".format(100*np.round(crr/(len(final_preds)),4)))

"""### Aggregating final results"""

# Predicted words on test set
spell_preds_test = []
for i in range(len(final_preds)):
    spell_preds_test.append(''.join((corr_list_sep_unique[np.argmax(final_preds[i])].split(' '))))

# True words in test set
source_word_indic_test = []
for i in range(0, len(final_preds)):
    source_word_indic_test.append(''.join(corr_list_sep[TRAIN_SPLIT+i].split(' ')))

# Words predicted by CTC model
ctc_output_test = []
for i in range(0, len(final_preds)):
    ctc_output_test.append(''.join(word_pred[TRAIN_SPLIT+i].split(' ')))

# CTC- accurate word predicted by CTC model
# Spell - Inaccurate prediction by CTC model corrected by Spell check model
# Uncorrected - Final prediction is incorrect
status_test = []
for i in range(0, len(final_preds)):
    if ctc_output_test[i]==source_word_indic_test[i]:
        status_test.append('CTC')
    elif spell_preds_test[i]==source_word_indic_test[i]:
        status_test.append('Spell')
    else:
        status_test.append('Uncorrected')

results_df = pd.DataFrame(list(zip(source_word_indic_test,ctc_output_test,spell_preds_test, status_test)),
                          columns=['Source Word (Indic)','CTC predicted word','Spell corrected word','Prediction status'])
# Store final results file
results_df.to_csv(path+'/results_df.csv')

