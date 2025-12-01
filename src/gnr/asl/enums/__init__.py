"""
Enums available in the GridWorks Application Shared Languages (ASL)

GridWorks ASL enables peer-to-peer shared vocabulary between energy system actors like 
SCADA devices, trading nodes, and market makers. Enums serve as the "controlled vocabulary" 
foundation that ensures everyone speaks the same language.

Key characteristics:
 - Immutable evolution: Enum values can be added but never changed or removed, ensuring 
   backwards compatibility across distributed systems
 - Transport-agnostic: Same enums work with RabbitMQ, HTTP APIs, Kafka, or any message delivery
 - Organizational autonomy: Each organization can build exactly the sophistication they need
   on top of shared foundations
 - Constitutional governance: Follow naming conventions (left.right.dot format) and 
   ownership rules defined in the ASL registry

Enums are the semantic building blocks that enable organizations to collaborate without 
compromising their independence. Unlike APIs where one party controls the vocabulary, 
ASL enums evolve through community governance while maintaining stability.

Application Shared Languages represent an evolution beyond traditional APIs - enabling 
true peer-to-peer collaboration where organizations maintain autonomy while sharing 
vocabulary, rather than client/server relationships where one party dictates the interface.

For more information:
 - [Why GridWorks ASL Exists](https://gridworks-asl.readthedocs.io/motivation/)
 - [ASL Rules and Guidelines](https://gridworks-asl.readthedocs.io/rules-and-guidelines/) 
 - [GridWorks ASL Overview](https://gridworks-asl.readthedocs.io/)
"""

from gnr.asl.enums.base_g_node_class import BaseGNodeClass
from gnr.asl.enums.g_node_status import GNodeStatus
from gnr.asl.enums.market_type_name import MarketTypeName


__all__ = [
    "BaseGNodeClass",
    "GNodeStatus",
    "MarketTypeName",
]
