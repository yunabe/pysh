# Copied from
# https://github.com/yunabe/practice/blob/master/python/misc/task_manager.py

import threading


class IdentityTask(object):
  def __init__(self, response):
    self.__response = response

  def start(self, cont):
    cont.done(self.__response)


class Controller(object):
    def __init__(self, runner, task, state, parent):
        self.__runner = runner
        self.__task = task
        self.__state = state
        self.__parent = parent
        self.__children = {}

    def add_child(self, child):
        self.__children[id(child)] = child

    def remove_child(self, child):
        del self.__children[id(child)]

    def children(self):
        return self.__children.values()

    def task(self):
        return self.__task

    def parent(self):
        return self.__parent

    def state(self):
        return self.__state

    def call(self, task, state):
        self.__runner.push_call(task, state, self)

    def done(self, response):
        self.__runner.push_done(response, self)

    def sync_call(self, task, state):
        self.__runner.sync_push_call(task, state, self)

    def sync_done(self, response):
        self.__runner.sync_push_done(response, self)


class Runner(object):
    def __init__(self, task):
        # tasks is FIFO to run tasks in DFS way.
        # To run tasks in BFS way, use collections.deque.
        self.__tasks = [('call', task, '<init>', None)]
        self.__root_cont = None
        self.response = None
        self.done = False
        self.__sync_tasks = []
        self.__cond = threading.Condition()

    def run(self):
        if not self.__tasks:
            self.__cond.acquire()
            while not self.__sync_tasks:
                self.__cond.wait()
            self.__tasks = self.__sync_tasks
            self.__sync_tasks = []
            self.__cond.release()

        while self.__tasks:
            self.run_internal()

    def __push_task(self, task):
        self.__tasks.append(task)

    def __sync_push_task(self, task):
        self.__cond.acquire()
        self.__sync_tasks.append(task)
        self.__cond.notify()
        self.__cond.release()

    def push_call(self, task, state, cont):
        self.__push_task(('call', task, state, cont))

    def sync_push_call(self, task, state, cont):
        self.__sync_push_task(('call', task, state, cont))

    def push_done(self, response, cont):
        self.__push_task(('done', response, cont))

    def sync_push_done(self, callstack, response):
        self.__sync_push_task(('done', response, cont))

    def __handle_exception(self):
        self.__call_dispose_recursively(self.__root_cont)

    def __call_dispose_recursively(self, cont):
        for child in cont.children():
            self.__call_dispose_recursively(child)
        task = cont.task()
        if hasattr(task, 'dispose'):
            task.dispose()

    def run_internal(self):
        task = self.__tasks.pop()
        type = task[0]
        if type == 'call':
            _, f, state, cont = task
            newcont = Controller(self, f, state, cont)
            if cont:
                cont.add_child(newcont)
            else:
                self.__root_cont = newcont
            try:
                f.start(newcont)
            except:
                self.__handle_exception()
                raise
        else:
            # 'done'
            _, response, cont = task
            parentcont = cont.parent()
            f = cont.task()
            if hasattr(f, 'dispose'):
                f.dispose()
            if not parentcont:
                self.response = response
                self.done = True
                self.__root_cont = None
            else:
                parentcont.remove_child(cont)
                try:
                    parentcont.task().resume(parentcont, cont.state(), response)
                except:
                    self.__handle_exception()
                    raise
