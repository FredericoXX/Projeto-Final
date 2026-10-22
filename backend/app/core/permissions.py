"""Matriz explícita de permissões por papel — o único sítio que a define.

Cada rota protegida declara a permissão de que precisa
(:func:`app.api.dependencies.auth.require_permission`) em vez de comparar o
papel diretamente. O papel continua a ser lido da base de dados em cada
pedido, nunca do token; esta matriz só traduz esse papel persistido num
conjunto fixo de permissões.

O que a matriz **não** faz, por desenho:

- não é um motor genérico de autorização nem uma hierarquia de papéis: nenhum
  papel herda de outro, e as permissões de cada um estão escritas por
  extenso;
- não decide o filtro por instituição nem a regra de posse. Esses continuam a
  ser aplicados em cada service a partir da identidade autenticada — uma
  permissão autoriza um *tipo* de operação, não o acesso a um recurso
  concreto;
- não concede leitura de conversas de terceiros a nenhum papel. Todas as
  contas acedem apenas às próprias conversas; não existe permissão
  equivalente a "ler as conversas da instituição".

Papéis:

- ``admin`` — administrador técnico **institucional**: contas, permissões,
  associações de identidade externa e configuração da própria instituição.
  Não gere documentos e não lê conversas de outros utilizadores. Não é um
  administrador global da plataforma;
- ``knowledge_manager`` — gestão documental (documentos, metadados, versões,
  processamento e vigência). Não gere contas nem consulta conversas ou
  registos académicos de terceiros;
- ``staff`` — base do futuro operador institucional. Nesta etapa tem apenas
  as próprias conversas; o acesso a casos atribuídos depende de um fluxo de
  atendimento que ainda não existe e não é simulado com acesso irrestrito;
- ``student`` — aluno;
- ``user`` — utilizador institucional genérico.

Curso, ano e situação académica são atributos de contexto, não papéis.
"""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    KNOWLEDGE_MANAGER = "knowledge_manager"
    STAFF = "staff"
    STUDENT = "student"
    USER = "user"


class Permission(StrEnum):
    # Contas da própria instituição: criar, listar, alterar papel e estado.
    USERS_MANAGE = "users.manage"
    # Leitura e configuração da própria instituição.
    INSTITUTION_MANAGE = "institution.manage"
    # Estabelecer ou remover a associação entre uma conta local e o
    # identificador externo estável do sistema académico.
    EXTERNAL_IDENTITY_MANAGE = "external_identity.manage"
    # Núcleo documental: documentos, metadados, versões, processamento,
    # conteúdo extraído e vigência.
    DOCUMENTS_MANAGE = "documents.manage"
    # Criar mensagens com role="system" nas próprias conversas.
    CONVERSATION_SYSTEM_MESSAGES = "conversations.system_messages"
    # Consultar os próprios pedidos académicos através da integração
    # institucional. Exige, além disto, uma associação de identidade externa.
    ACADEMIC_REQUESTS_READ_OWN = "academic_requests.read_own"


# Permissões comuns a todas as contas autenticadas — conversas próprias,
# perguntas fundamentadas, pesquisa de evidência e encaminhamento E1 — não
# estão na matriz: dependem apenas de autenticação e da regra de posse.
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(
        {
            Permission.USERS_MANAGE,
            Permission.INSTITUTION_MANAGE,
            Permission.EXTERNAL_IDENTITY_MANAGE,
            Permission.CONVERSATION_SYSTEM_MESSAGES,
        }
    ),
    Role.KNOWLEDGE_MANAGER: frozenset({Permission.DOCUMENTS_MANAGE}),
    Role.STAFF: frozenset(),
    Role.STUDENT: frozenset({Permission.ACADEMIC_REQUESTS_READ_OWN}),
    Role.USER: frozenset({Permission.ACADEMIC_REQUESTS_READ_OWN}),
}

ALLOWED_ROLES: frozenset[str] = frozenset(role.value for role in Role)


def permissions_for_role(role: str) -> frozenset[Permission]:
    """Permissões de um papel persistido; um papel desconhecido não tem nenhuma.

    Falhar fechado aqui é defesa em profundidade: a constraint da base de
    dados e os schemas já recusam papéis fora de :class:`Role`.
    """
    try:
        return ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return frozenset()


def has_permission(role: str, permission: Permission) -> bool:
    return permission in permissions_for_role(role)
