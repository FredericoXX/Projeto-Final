"""Revalidação da conta autenticada no ponto sensível de cada operação.

``get_current_user`` relê o papel e o estado no início do pedido, mas isso não
basta: entre essa leitura e a operação, outra transação pode desativar a conta,
alterar-lhe o papel ou desativar a instituição. Sem revalidar, o pedido em
curso completaria com uma autorização que já foi revogada.

:func:`revalidate_actor` fecha essa janela. Relê a instituição e a conta **sob
lock**, na transação da própria operação e pela mesma ordem dos restantes
fluxos — instituição → utilizador → recurso —, e devolve a conta persistida. O
papel avaliado a seguir é sempre o desta releitura, nunca o do objeto recebido.

Os locks são ``FOR SHARE`` por omissão: bastam para que uma revogação
concorrente (um ``UPDATE`` dessas linhas) espere pelo fim da operação, ou seja
vista por ela se já tiver feito commit, e não serializam operações da mesma
conta entre si. As mutações que alteram a própria instituição ou contas pedem
``exclusive_institution=True``: o ``FOR UPDATE`` da instituição serializa-as e
evita que dois locks partilhados tenham de ser promovidos em simultâneo.

Os locks duram até ao fim da transação. Por isso nenhum fluxo os mantém durante
uma chamada externa: quem consulta um fornecedor revalida antes, termina a
transação, chama a fonte e volta a revalidar antes de entregar o resultado.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.permissions import Permission, has_permission
from app.models.institution import Institution
from app.models.user import User

INVALID_TOKEN_MESSAGE = "Invalid authentication token."
MISSING_PERMISSION_MESSAGE = "This account does not have the required permission."


def revalidate_actor(
    db: Session,
    *,
    user_id: uuid.UUID,
    institution_id: uuid.UUID,
    permission: Permission | None = None,
    exclusive_institution: bool = False,
) -> User:
    """Relê e bloqueia instituição e conta; devolve a conta persistida.

    Recebe identificadores escalares, e não o objeto ``User`` da autenticação,
    para que nenhum atributo desse objeto possa ser usado por engano depois da
    revalidação. Uma conta ou instituição inativa — ou inexistente — responde
    como token inválido (401), tal como na autenticação; um papel que já não
    tem a permissão pedida responde 403.
    """
    institution = db.scalar(
        select(Institution)
        .where(Institution.id == institution_id, Institution.is_active.is_(True))
        .with_for_update(read=not exclusive_institution)
        .execution_options(populate_existing=True)
    )
    if institution is None:
        raise AuthenticationError(INVALID_TOKEN_MESSAGE)

    actor = db.scalar(
        select(User)
        .where(
            User.id == user_id,
            User.institution_id == institution_id,
            User.is_active.is_(True),
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if actor is None:
        raise AuthenticationError(INVALID_TOKEN_MESSAGE)

    if permission is not None and not has_permission(actor.role, permission):
        raise AuthorizationError(MISSING_PERMISSION_MESSAGE)
    return actor
