from datetime import datetime
from typing import Callable, Union

from app.text_parsers import format_date, trim_text

class TextFormatter:

    name: str
    date_time_format: str
    name_formatter: Union[Callable[[str], str], None] = None
    derived_instances: dict[str, 'TextFormatter'] = {}
    
    def __init__(self, **kwargs):
        self.name = kwargs.get("name", "default")
        self.date_time_format = kwargs.get("date_time_format", "%d.%m.%Y %H:%M:%S")
        self.name_formatter = kwargs.get("name_formatter", None)

    def format_date(self, date: datetime) -> str:
        """
        Formats a datetime object to a string using the specified date_time_format.
        """
        return format_date(date, self.date_time_format)
    
    def format_name(self, name: Union[str, None]) -> str:
        
        if name is None:
            return ""
        
        if self.name_formatter is not None:
            return self.name_formatter(name)
        
        return trim_text(name)
    

    def get_instance(self, **kwargs):
        """
        Retrieve or create a new TextFormatter instance with the specified parameters.
        Use self as base for the new instance and override by passing new parameters.
        """
        kwargs.setdefault("name", "default")
        kwargs.setdefault("date_time_format", self.date_time_format)
        kwargs.setdefault("name_formatter", self.name_formatter)

        instance_key = f"TextFormatter::{kwargs['name']}"

        if instance_key in self.derived_instances:
            return self.derived_instances[instance_key]

        self.derived_instances[instance_key] = TextFormatter(**kwargs)

        return self.derived_instances[instance_key]
