import time

def perf_clock():
    if hasattr(time, 'clock'):
        return time.clock()
    elif hasattr(time, 'perf_counter'):
        return time.perf_counter()
    else:
        raise Exception("Python time lib doesn't contain a suitable clock function")