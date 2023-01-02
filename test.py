import random
from time import time

from semirandom import randint

start_time = time()
for i in range(1000000):
    random.randint(0, 10)
random_time = time() - start_time

start_time = time()
for i in range(1000000):
    randint(10)
semirandom_time = time() - start_time

print(f"Random time: {random_time}")
print(f"Semi-Random time: {semirandom_time}")
