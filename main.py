# -*- coding: utf-8 -*-
"""DL_project.ipynb

Automatically generated by Colaboratory.
You must arrange the files in order to run them 
"""

# THE FIRST CODE BLOCK USES SAVED MODELS TO RECOGNIZE THE EMOTION IN THE IMAGE AND GENERATE THE MUSIC
# SECOND CODE BLOCK IS FOR FULL EMOTION RECOGNITION SOURCE CODE
# THIRD CODE BLOCK IS FOR FULL MUSIC GENERATION SOURCE CODE

################################################################################
#                   EMOTION RECOGNITION PART FROM SAVED MODEL                  #
################################################################################

from keras.preprocessing.image import load_img, img_to_array
import numpy as np
import keras
from keras.preprocessing.image import ImageDataGenerator
from keras.layers import Dense,Input,Dropout,Flatten,Conv2D,BatchNormalization,Activation,MaxPooling2D
from keras.models import Model,Sequential
from keras.optimizers import Adam,SGD,RMSprop


saved_model_path  = '/content/drive/MyDrive/keras_models/emotion_recognition_2.keras' # take saved weights of the NN from drive as keras file
new_image_path = "/content/drive/MyDrive/emotions_dataset/predict" # take the input from the drive folder in this directory

#load the model from drive
model = keras.models.load_model(saved_model_path)
datagen_predict  = ImageDataGenerator()

predict_image_generator = datagen_predict.flow_from_directory(
        directory=new_image_path,
        target_size=(48, 48),
        color_mode="grayscale",
        shuffle = False,
        class_mode='categorical',
        batch_size=1)


filenames = predict_image_generator.filenames # predict the emotion in input image
nb_samples = len(filenames)
batch_size = 256
predictions = model.predict_generator(predict_image_generator,steps = np.ceil(nb_samples/batch_size))
print(predictions)


# Get the predicted class index
predicted_class_index = np.argmax(predictions)

# Map the index to the corresponding emotion label
emotion_labels = ["angry",  "happy", "neutral", "sad"]
predicted_emotion = emotion_labels[predicted_class_index]

print("Predicted Emotion:", predicted_emotion)



###############################################################################################
###############################################################################################
###############################################################################################

###############################################################################################
#                              MUSIC GENERATION PART FROM SAVED MODEL                         #
###############################################################################################
try:
  import fluidsynth
except ImportError:
  !pip install fluidsynth
  import fluidsynth

try:
  import pretty_midi
except ImportError:
  !pip install pretty_midi
  import pretty_midi

import collections
import datetime
import fluidsynth
import glob
import numpy as np
import pathlib
import pandas as pd
import pretty_midi
import seaborn as sns
import tensorflow as tf
import keras
from IPython import display
from matplotlib import pyplot as plt
from typing import Optional



seed = 42
tf.random.set_seed(seed)
np.random.seed(seed)

# Sampling rate for audio playback
_SAMPLING_RATE = 16000
seq_length = 25
vocab_size = 128
key_order = ['pitch', 'step', 'duration']

# convert the data in midi format to notes to feed them as input
def midi_to_notes(midi_file: str) -> pd.DataFrame:
  pm = pretty_midi.PrettyMIDI(midi_file)
  instrument = pm.instruments[0]
  notes = collections.defaultdict(list)

  # Sort the notes by start time
  sorted_notes = sorted(instrument.notes, key=lambda note: note.start)
  prev_start = sorted_notes[0].start

  # convert midi to nodes
  for note in sorted_notes:
    start = note.start
    end = note.end
    notes['pitch'].append(note.pitch)
    notes['start'].append(start)
    notes['end'].append(end)
    notes['step'].append(start - prev_start)
    notes['duration'].append(end - start)
    prev_start = start

  return pd.DataFrame({name: np.array(value) for name, value in notes.items()})

import random
# create the notes from a randomly choosen music in midi files so that each time a new note sequence will be given as input and new music will be generated
def create_raw_notes(emotion):

  # take a music randomly from this location
  data_dir = pathlib.Path("/content/drive/MyDrive/music_dataset_2/midi_files/"+emotion+"/")
  filenames = glob.glob(str(data_dir/'**/*.mid*'))
  #print('Number of files:', len(filenames))
  random_music_index = random.randint(0, len(filenames)-1)

  # choose a random music from the midi files in drive folder to use its notes to generate a new music from the model
  sample_file = filenames[random_music_index]
  print(sample_file.split("/")[-1]," is choosen as input out of ", len(filenames)," files.")

  # use pretty_midi library to handle midi files
  pm = pretty_midi.PrettyMIDI(sample_file)

  # convert midi fata to notes
  raw_notes = midi_to_notes(sample_file)
  raw_notes.head()

  return raw_notes

# convert notes to midi data to again generate a music from predicted inputs
def notes_to_midi(
  notes: pd.DataFrame,
  out_file: str,
  instrument_name: str,
  velocity: int = 100,  # note loudness
  ) -> pretty_midi.PrettyMIDI:

  pm = pretty_midi.PrettyMIDI()
  instrument = pretty_midi.Instrument(
      program=pretty_midi.instrument_name_to_program(
          instrument_name))

  prev_start = 0
  for i, note in notes.iterrows():
    start = float(prev_start + note['step'])
    end = float(start + note['duration'])
    note = pretty_midi.Note(
        velocity=velocity,
        pitch=int(note['pitch']),
        start=start,
        end=end,
    )
    instrument.notes.append(note)
    prev_start = start

  pm.instruments.append(instrument)
  pm.write(out_file)
  return pm




@keras.saving.register_keras_serializable()
def mse_with_positive_pressure(y_true: tf.Tensor, y_pred: tf.Tensor):
  mse = (y_true - y_pred) ** 2
  positive_pressure = 10 * tf.maximum(-y_pred, 0.0)
  return tf.reduce_mean(mse + positive_pressure)


# given a notes of sequence, this function will predict the next node
def predict_next_note(
    notes: np.ndarray,
    model: tf.keras.Model,
    temperature: float = 1.0) -> tuple[int, float, float]:
  """Generates a note as a tuple of (pitch, step, duration), using a trained sequence model."""

  assert temperature > 0

  # Add batch dimension
  inputs = tf.expand_dims(notes, 0)

  predictions = model.predict(inputs)
  pitch_logits = predictions['pitch']
  step = predictions['step']
  duration = predictions['duration']

  pitch_logits /= temperature
  pitch = tf.random.categorical(pitch_logits, num_samples=1)
  pitch = tf.squeeze(pitch, axis=-1)
  duration = tf.squeeze(duration, axis=-1)
  step = tf.squeeze(step, axis=-1)

  # `step` and `duration` values should be non-negative
  step = tf.maximum(0, step)
  duration = tf.maximum(0, duration)

  return int(pitch), float(step), float(duration)


# generate the music from the saved model, the notes of randomly choosen music will be given as input to this function and next num_predicitons notes will be predicted iteratively
def generate_music(raw_notes, model):


  temperature = 2 # controls the randomness of predicted node since the output note with highest probability can cause repetative notes as a result
  num_predictions = 120 # specifies the number of notes that will be predicted

  sample_notes = np.stack([raw_notes[key] for key in key_order], axis=1)

  # The initial sequence of notes; pitch is normalized similar to training
  # sequences
  input_notes = (
      sample_notes[:seq_length] / np.array([vocab_size, 1, 1]))

  generated_notes = []
  prev_start = 0
  for _ in range(num_predictions):
    pitch, step, duration = predict_next_note(input_notes, model, temperature)
    ################# THIS IS A CRUICAL PART SINCE I EXPAND THE DURATION AND STEP TO GENERATE A MORE COMPREHENSIBLE MUSIC, OTHERWISE IT SOMETIMES GENERATES MUSICS AS 1 SECOND LONG
    # we specifiy the duration, starting and ending points in the generated music on following lines
    step, duration = step*10, duration*10
    start = prev_start + step
    end = start + duration
    input_note = (pitch, step, duration)
    generated_notes.append((*input_note, start, end))
    input_notes = np.delete(input_notes, 0, axis=0)
    input_notes = np.append(input_notes, np.expand_dims(input_note, 0), axis=0) # new input nodes is updated by adding the new output node
    prev_start = start

  generated_notes = pd.DataFrame(
      generated_notes, columns=(*key_order, 'start', 'end'))



  generated_notes.head(10)

  out_file = 'output.mid'
  out_pm = notes_to_midi(
      generated_notes, out_file=out_file, instrument_name="Acoustic Grand Piano")#instrument_name=instrument_name

  from google.colab import files
  files.download(out_file) # download the midi file to computer



# emotion_results = [1,2,3,4]
# max_value = max(emotion_result)
# max_index = emotion_result.index(max_value)

saved_model_path_happy  = '/content/drive/MyDrive/keras_models/music_generator_happy.keras'
saved_model_path_sad  = '/content/drive/MyDrive/keras_models/music_generator_sad.keras'
saved_model_path_angry  = '/content/drive/MyDrive/keras_models/music_generator_angry.keras'
saved_model_path_relax  = '/content/drive/MyDrive/keras_models/music_generator_relax.keras'


#emotion_labels = ["angry",  "happy", "neutral", "sad"]

# if you change the following variable, you can generate specific types of musics based on the emotion in that index
#predicted_class_index = 3



# it will only generate music based on the emotion recognized by the CNN
if(predicted_class_index==0):
  print("Predicted emotion from the image is angry and corresponding music is being generated")
  model_angry_2 = keras.models.load_model(saved_model_path_angry) #load the model from drive
  raw_notes_angry = create_raw_notes("angry")
  generate_music(raw_notes_angry, model_angry_2)

elif(predicted_class_index==1):
  print("Predicted emotion from the image is happy and corresponding music is being generated")
  model_happy_2 = keras.models.load_model(saved_model_path_happy)
  raw_notes_happy = create_raw_notes("happy")
  generate_music(raw_notes_happy, model_happy_2)

elif(predicted_class_index==2):
  print("Predicted emotion from the image is relax and corresponding music is being generated")
  model_relax_2 = keras.models.load_model(saved_model_path_relax)
  raw_notes_relax = create_raw_notes("relax") # relax instead of neutral in images
  generate_music(raw_notes_relax, model_relax_2)

elif(predicted_class_index==3):
  print("Predicted emotion from the image is sad and corresponding music is being generated")
  model_sad_2 = keras.models.load_model(saved_model_path_sad)
  raw_notes_sad = create_raw_notes("sad")
  generate_music(raw_notes_sad, model_sad_2)