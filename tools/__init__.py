"""Tools semânticas do SIGA Needle Expert (P05-T02, ADR-013/014 em docs/06).

Exporta as 5 tools semânticas visíveis ao nano coprocessador:
- `siga_locate`: Localiza arquivos/símbolos de uma funcionalidade
- `siga_trace`: Traça fluxo endpoint→controller→negócio→entidade→persistência→view
- `siga_impact`: Efeitos de modificar arquivo/classe/método/feature
- `siga_history`: Mudanças semelhantes e co-change no Git
- `siga_context`: Cápsula final mínima para a IA grande
"""

from tools.siga_context import siga_context
from tools.siga_history import siga_history
from tools.siga_impact import siga_impact
from tools.siga_locate import siga_locate
from tools.siga_trace import siga_trace

__all__ = [
    "siga_locate",
    "siga_trace",
    "siga_impact",
    "siga_history",
    "siga_context",
]
