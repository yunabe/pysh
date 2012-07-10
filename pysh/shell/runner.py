import pysh.shell.builtin
import pysh.shell.evaluator

pysh.shell.builtin.register_builtin()

def run(cmd_str, globals, locals, responses=None):
  rc = pysh.shell.evaluator.run(cmd_str, globals, locals)
  if not responses:
    return None
  result = []
  for response in responses:
    result.append(rc[response] if response in rc else None)
  return tuple(result)
