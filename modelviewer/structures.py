class CaseInsensitiveKey(object):
    """
    A wrapper class for creating case-insensitive keys for dictionary-like operations.

    This class allows keys to be compared and hashed in a case-insensitive manner 
    by using the casefold() method, which provides a more comprehensive case-folding 
    than lower() for international character comparisons.

    Attributes:
        key (str): The original key string.
    """
    def __init__(self, key):
        """
        Initialize the CaseInsensitiveKey with a given key.

        Args:
            key (str): The key to be stored.
        """
        self.key = key

    def __hash__(self):
        """
        Generate a hash value for the key using its case-folded version.

        Returns:
            int: A hash value that is consistent for keys with different cases.
        """
        return hash(self.key.casefold())

    def __eq__(self, other):
        """
        Compare two keys for equality in a case-insensitive manner.

        Args:
            other (CaseInsensitiveKey): Another key to compare with.

        Returns:
            bool: True if keys are equal when case-folded, False otherwise.
        """
        return self.key.casefold() == other.key.casefold()

    def __str__(self):
        """
        Return the string representation of the key.

        Returns:
            str: The original key string.
        """
        return self.key


class CaseInsensitiveDict(dict):
    """
    A dictionary subclass that allows case-insensitive key operations.

    This dictionary treats keys as case-insensitive, meaning 'Key' and 'key' 
    are considered the same key when setting, getting, or checking for existence.

    Inherits all standard dictionary methods with case-insensitive key handling.
    """
    def __setitem__(self, key, value):
        """
        Set an item in the dictionary using a case-insensitive key.

        Args:
            key (str): The key to set.
            value: The value to associate with the key.
        """
        key = CaseInsensitiveKey(key)
        super(CaseInsensitiveDict, self).__setitem__(key, value)

    def __getitem__(self, key):
        """
        Retrieve an item from the dictionary using a case-insensitive key.

        Args:
            key (str): The key to retrieve.

        Returns:
            The value associated with the key.

        Raises:
            KeyError: If the key is not found.
        """
        key = CaseInsensitiveKey(key)
        return super(CaseInsensitiveDict, self).__getitem__(key)

    def __contains__(self, key):
        """
        Check if a key exists in the dictionary in a case-insensitive manner.

        Args:
            key (str): The key to check.

        Returns:
            bool: True if the key exists, False otherwise.
        """
        key = CaseInsensitiveKey(key)
        return super(CaseInsensitiveDict, self).__contains__(key)

    def get(self, key, default=None):
        """
        Retrieve an item from the dictionary using a case-insensitive key.

        Args:
            key (str): The key to retrieve.
            default: The value to return if the key is not found (defaults to None).

        Returns:
            The value associated with the key, or the default value if not found.
        """
        key = CaseInsensitiveKey(key)
        return super(CaseInsensitiveDict, self).get(key, default)
