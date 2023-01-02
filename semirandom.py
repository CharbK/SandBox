import random

NUMBERS = [*range(1024)]
random.shuffle(NUMBERS)
NUMBERS = tuple(NUMBERS)

LAST_PLACE = len(NUMBERS) - 1
CURSOR = -1


def randint(max_num: int):
    
    global CURSOR
    if CURSOR == LAST_PLACE:
        CURSOR = 0
    else:
        CURSOR += 1
    return NUMBERS[CURSOR] % max_num