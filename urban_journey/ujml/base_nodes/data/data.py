import re

from urban_journey.ujml.data_base import DataNodeBase
from urban_journey.ujml.exceptions import InvalidInputError
from urban_journey.common.cached import cached
from urban_journey.ujml.attributes import bool_t

is_list_regex = re.compile(r"(?:\[[\s\S]*?\])|(?:\([\s\S]*?\))|(?:\{[\s\S]*?\})|(,|;)")
to_2d_list_regex = re.compile(r"(?:^|; *)([\s\S]*?)(?:$|(?=;))")


class data(DataNodeBase):
    ndarray = bool_t(optional_value=True)

    @cached
    def data(self):
        # Check if there are child elements.
        if len(self.children):
            # There are child elements. Check if they have a data attribute.
            for child in self.children:
                # This is a valid data element. So just return the data it contains.
                try:
                    return child.data
                except AttributeError:
                    pass
            # No valid data element was found. raise error.
            self.raise_exception(InvalidInputError, self.tag)
        else:
            # There are no elements in here. So there is probably some text to evaluate as python code.
            source = self.element.text
            if source is not None:
                # There is text in this element. Evaluate it as python code. Check if it's a list and then evaluate it.
                source = self.process_if_array(source, self.ndarray)
                return self.root.interpreter.eval(source,
                                                  self.file_name,
                                                  self.source_line)
            else:
                # There is neither code nor a data element in this input. Raise an error.
                self.raise_exception(InvalidInputError, self.tag)

    @staticmethod
    def process_if_array(source, is_ndarray):
        source = source.strip()
        t = 0
        for m in is_list_regex.finditer(source):
            if m.group(1) == ",":
                t = 1
            if m.group(1) == ";":
                t = 2
                break
        if t == 0:
            return source

        if t == 2:
            (source, n) = to_2d_list_regex.subn(r"[\1],", source)

        if is_ndarray:
            source = "np.array([%s])" % (source,)
        else:
            source = "[%s]" % (source,)

        return source