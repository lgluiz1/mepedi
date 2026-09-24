import sys

# Compatibilidade do Django 5.1 com Python 3.14 (correção do copy no BaseContext)
if sys.version_info >= (3, 14):
    try:
        from django.template.context import BaseContext
        def _compat_base_context_copy(self):
            duplicate = object.__new__(self.__class__)
            duplicate.dicts = self.dicts[:]
            return duplicate
        BaseContext.__copy__ = _compat_base_context_copy
    except ImportError:
        pass
