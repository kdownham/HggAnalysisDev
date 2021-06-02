from tensorflow import keras
from tensorflow.keras import layers
import tensorflow
import numpy

from . import logger
from . import regression_model


class NNHelper():
    def __init__(self, **kwargs):
        self.events = kwargs.get("events")
        self.config = kwargs.get("config")
        self.output_tag = kwargs.get("output_tag", "")
        self.debug = kwargs.get("debug")
        self.load_from_disk = kwargs.get("load_from_disk")
        self.made_tensor = False
        if self.load_from_disk:
            keras.models.load_model("outputs/{}_model.h5")
        else:
            # self.model = self.init_network()
            self.model = regression_model.TauRegressionModel(self.config["mva"])

    def init_network(self):
        n_hidden = self.config["mva"]["param"]["n_hidden"]
        n_input = self.config["mva"]["param"]["n_input"]
        n_output = self.config["mva"]["param"]["n_output"]

        """ Every hidden layer provides the following
        1. Number of output dimension neurons
        2. Activation function (relu default)"""

        model = keras.Sequential()
        model.add(layers.InputLayer(input_shape=(n_input,)))
        for i in range(1, n_hidden):
            layer_info = self.config["mva"]["param"]["layer_{}".format(i)]
            n_neurons = layer_info["n_neurons"]
            if "activation" not in layer_info.keys():
                activation = "relu"
            else:
                activation = layer_info["activation"]
            model.add(layers.Dense(n_neurons, activation=activation, name="layer_{}".format(i)))

        # output layer
        model.add(layers.Dense(n_output, name="output"))

        return model

    def train(self):
        if not self.made_tensor:
            self.make_tensor()
        if self.debug > 0:
            print("[DNNHelper] Training the following DNN")
            self.model.summary()
        n_max_epochs = self.config["mva"]["n_max_epochs"]
        if self.config["mva"]["early_stopping"]:
            n_early_stopping = self.config["mva"]["early_stopping_roungs"]
            print("[DNNHelper] Early stopping with {} rounds ({} maximum)".format(n_early_stopping, n_max_epochs))
        else:
            print("[DNNHelper] Training for {} (no early stopping)".format(n_max_epochs))
            n_early_stopping = -1

        loss_function = keras.losses.MeanSquaredError(n_early_stopping)
        optimizer = keras.optimizers.Adam(learning_rate=1e-3)
        logging = logger.Logger(n_early_stopping)
        # training happens here!
        for epoch in range(n_max_epochs):
            for step, (features, targets) in enumerate(self.events["train"]["tensor"]):
                with tensorflow.GradientTape() as tape:
                    outputs = self.model(features)
                    loss_value = loss_function(targets, outputs)

                logging.update_train_loss(epoch, step, loss_value, (self.debug > 0))

                # do backprop to compute gradients
                gradients = tape.gradient(loss_value, self.model.trainable_weights)
                # do gradient descent
                optimizer.apply_gradients(zip(gradients, self.model.trainable_weights))

            # accuracy measure after every epoch
            validation_loss = 0
            val_dataset_length = 0
            for step, (features, targets) in enumerate(self.events["test"]["tensor"]):
                outputs = self.model(features)
                val_dataset_length += len(targets)
                validation_loss += loss_function(targets, outputs) * len(targets)
            validation_loss /= val_dataset_length
            # in addition to updating validation loss, this function will trigger the early stopping
            early_stop = logging.update_val_loss(epoch, validation_loss, (self.debug > 0))
            if early_stop:
                print("Early stopping!")
                break
        logging.save_losses()

    def make_tensor(self, batch_size=256):
        for split in self.events.keys():
            x = self.events[split]["X"]
            y = self.events[split]["Y"]
            if batch_size < 0:
                self.events[split]["tensor"] = tensorflow.data.Dataset.from_tensor_slices((x, y))
            else:
                self.events[split]["tensor"] = tensorflow.data.Dataset.from_tensor_slices((x, y)).batch(batch_size)
            self.made_tensor = True

    def predict(self, test_data):
        """ For inference. Assumes fully loaded or trained model at disposal"""
        if not self.made_tensor:
            self.make_tensor()
        prediction = {}
        for split in self.events.keys():
            for step, (features, targets) in enumerate(self.events[split]["tensor"]):
                if split not in self.prediction.keys():
                    self.prediction[split] = self.model(features).numpy().reshape(-1)
                else:
                    self.prediction[split] = numpy.append(self.prediction[split], self.model(features).numpy().reshape(-1))

        return prediction

    def save_model(self):
        """ Save weights"""
        self.model_save("outputs/{}_model.h5")