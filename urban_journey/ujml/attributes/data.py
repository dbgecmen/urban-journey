from urban_journey.ujml.unique import Required
from urban_journey.ujml.exceptions import UJMLTypeError, InvalidShapeError, MissingRequiredInput
from collections import  defaultdict


import numpy as np


class Data(object):
    """Used to declare a data input child nodes. The child nodes will be of type
       :class:`urban_journey.ujml.nodes.data.data.data` and will thus behave the same as a :ref:`data_node_section` node.

       :param type: Required data type.
       :param optional_value: Optional value to return in case the node was not given in the ujml file.
       :param shape: Check the shape of an array. The data must be a numpy.ndarray. Pass 'nan' to skip checking a dimension.
    """

    # TODO: Add name as a parameter.
    def __init__(self, type=None, optional_value=Required, shape=None):
        self.type = type
        self.optional_value = optional_value
        self.shape = shape
        self.name = None
        self.child_cache = defaultdict(lambda: None)

    def __get__(self, instance, owner):
        """
        Returns the data that this descriptor represents.

        :param instance: Instance of the owner class that is requesting the data.
        :param owner: Class that owns this instance of the descriptor.
        :return: Data being requested.
        """
        # If the descriptor object is being requested from the class, return the descriptor itself.
        if instance is None:
            return self

        # If the name of the descriptor is unknown find it.
        if self.name is None:
            self.get_name(owner)

        # If the child element that this descriptor connects to is still unknown, find it.
        if self.child_cache[instance] is None:
            for child in instance:
                if child.tag == self.name:
                    self.child_cache[instance] = child

        child = self.child_cache[instance]

        if child is not None:
            # If the child element was found, validate the data it contains and return it.
            return self.validate(child, child.data)
        else:
            # Else check whether it's optional and return the optional data. If it's required, raise exception.
            if self.optional_value is Required:
                instance.raise_exception(MissingRequiredInput, instance.tag, self.name)
            else:
                return self.optional_value

    def get_name(self, owner):
        """
        Loops through all members of the owner class to find this descriptors name.

        :param owner: Owner class
        :return: Name of this descriptor inside the owner class
        """
        for key, value in owner.__dict__.items():
            if value is self:
                self.name = key
        assert self.name

    def validate(self, instance, data):
        """
        Checks the type and size of the data if needed.
        :param instance: Instance of the owner class that is requesting data.
        :param data: Data to be validated.
        :return: The data if it's valid, otherwise it raises either a class:`urban_journey.exceptions.UJMLTypeError` or
           class:`urban_journey.exceptions.InvalidShapeError`
        """
        if self.type is not None:
            if not isinstance(data, self.type):
                instance.raise_exception(UJMLTypeError, self.name)
        if self.shape is not None:
            # Data type must be numpy array if checking for type.
            if not isinstance(data, np.ndarray):
                instance.raise_exception(UJMLTypeError, self.name)
            shape = data.shape
            if len(shape) != len(self.shape):
                instance.raise_exception(InvalidShapeError, self.name)
            else:
                for s1, s2 in zip(shape, self.shape):
                    if not np.isnan(s2):
                        if s1 != s2:
                            instance.raise_exception(InvalidShapeError, self.name)
        return data
