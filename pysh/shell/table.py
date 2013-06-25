import StringIO
import tokenize

class VarDict(object):
    def __init__(self, locals, row):
        self.__row = row
        self.__locals = locals

    def __getitem__(self, key):
        if not self.__locals:
            return self.__row[key]
        try:
            return self.__row[key]
        except KeyError:
            return self.__locals[key]


def CreateTableFromIterableRows(rows):
    it = iter(rows)
    try:
        row0 = it.next()
    except StopIteration:
        return PyshTable((), ())
    table = row0.table()
    def values_generator():
        yield row0.values()
        while True:
            row = it.next()
            assert row.table() is table
            yield row.values()

    return PyshTable(table.columns, values_generator())


class PyshTable(object):
    def __init__(self, cols, values_generator):
        assert isinstance(cols, tuple)
        self.__cols = cols
        self.__generator = values_generator
        self.__col_index = {}
        for i, col in enumerate(cols):
            self.__col_index[col] = i

    def col_index(self, col):
        return self.__col_index[col]

    def __iter__(self):
        return self.rows.__iter__()

    @property
    def columns(self):
        return self.__cols

    @property
    def rows(self):
        return (Row(self, values) for values in self.__generator)

    def pretty_print(self, writer, sep=' |'):
        # key -> len(key)
        max_width = dict(zip(self.__cols, map(len, self.__cols)))
        rows = list(self.rows)
        for row in rows:
            for col in self.__cols:
                value = row[col]
                max_width[col] = max(max_width[col], len(str(value)))
        for i, col in enumerate(self.__cols):
            if i != 0:
                writer.write(sep)
            writer.write(('%% %ds' % max_width[col]) % col)
        writer.write('\n')
        writer.write('-' * reduce(lambda x, y: x + y + len(sep),
                                  max_width.values()))
        writer.write('\n')
        for row in rows:
            for i, col in enumerate(self.__cols):
                if i != 0:
                    writer.write(sep)
                writer.write(('%% %ds' % max_width[col]) % str(row[col]))
            writer.write('\n')

    def where(self, cond, globals=None, locals=None):
        return PyshTable(
            self.__cols,
            self.__where_generator(cond, self.rows, globals, locals))

    def __where_generator(self, cond, rows, globals, locals):
        for row in rows:
            if eval(cond, globals, VarDict(locals, row)):
                yield row.values()

    def orderby(self, order, asc=True, globals=None, locals=None):
        orders = []
        rows = list(self.rows)
        for i, row in enumerate(rows):
            orders.append((eval(order, globals, VarDict(locals, row)), i))
        if asc:
            comparator = cmp
        else:
            comparator = lambda x, y: cmp(y, x)
        orders.sort(comparator)
        return PyshTable(self.__cols, (rows[i].values() for _, i in orders))

    def select(self, expr, globals=None, locals=None):
        parser = SelectExprParser(expr)
        entries = parser.parse()
        cols = tuple((e[1] if e[1] else e[0] for e in entries))
        def generator():
            for row in self.rows:
                values = []
                for entry, _ in entries:
                    values.append(eval(entry, globals, VarDict(locals, row)))
                yield values
        return PyshTable(cols, generator())


class Row(object):
    def __init__(self, table, values):
        self.__table = table
        self.__values = values

    def table(self):
        return self.__table

    def values(self):
        return self.__values

    def __getitem__(self, key):
        return self.__values[self.__table.col_index(key)]

    def __getattr__(self, key):
        return self.__getitem__(key)

    def __setattribute__(self, key, value):
        self.__values[self.__table.col_index(key)] = value


class SelectExprParser(object):
    """A parser to separate select expr.

    parse returns a list of pairs of (expr, as).
    """
    
    def __init__(self, expr):
        self.__expr = expr

    def parse(self):
        entries = self.separate_by_commma(self.__expr)
        return [self.extract_as(entry) for entry in entries]

    def separate_by_commma(self, expr):
        tokens = tokenize.generate_tokens(
            StringIO.StringIO(expr).readline)
        results = []
        level = 0
        current = []
        for token in tokens:
            if token[1] == '(' or token[1] == '[' or token[1] == '{':
                level += 1
            elif token[1] == ')' or token[1] == ']' or token[1] == '}':
                level -= 1
            elif (level == 0 and token[1] == ',' or
                  token[0] == tokenize.ENDMARKER):
                results.append(current)
                current = []
                continue
            current.append(token)
        return results

    def extract_as(self, entry):
        if (entry[-1][0] == tokenize.STRING and
            len(entry) > 1 and entry[-2][0] == tokenize.NAME and
            entry[-2][1] == 'as'):
            return self.tokens_to_str(entry[:-2]), eval(entry[-1][1])
        if (entry[-1][0] == tokenize.NAME and
            len(entry) > 1 and entry[-2][0] == tokenize.NAME and
            entry[-2][1] == 'as'):
            return self.tokens_to_str(entry[:-2]), entry[-1][1]
        return self.tokens_to_str(entry), None
    
    def tokens_to_str(self, tokens):
        prev_end = None
        out = StringIO.StringIO()
        for token in tokens:
            if token[0] == tokenize.ENDMARKER:
                continue
            if prev_end and prev_end != token[2]:
                out.write(' ')
            out.write(token[1])
            prev_end = token[3]
        return out.getvalue()
