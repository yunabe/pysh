
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

