import sys
from dataclasses import dataclass, field

from analisador_lexico import Lexer, Token


@dataclass
class ASTNode:
    kind: str
    value: object = None
    children: list = field(default_factory=list)
    line: int = None
    column: int = None

    def add(self, child):
        if child is not None:
            self.children.append(child)
        return self

    def pretty(self, level=0):
        espaco = "  " * level
        valor = f": {self.value}" if self.value is not None else ""
        texto = f"{espaco}{self.kind}{valor}\n"

        for child in self.children:
            if isinstance(child, ASTNode):
                texto += child.pretty(level + 1)
            else:
                texto += f"{'  ' * (level + 1)}{child}\n"

        return texto


class ParseError(Exception):
    pass


@dataclass
class Symbol:
    name: str
    type: str
    category: str
    scope: str
    params: list = field(default_factory=list)


class Parser:
    TYPES = {"int", "float", "char", "void", "bool", "string"}
    STATEMENT_STARTERS = {
        "if", "while", "for", "return", "break", "continue",
        "int", "float", "char", "void", "bool", "string"
    }

    def __init__(self, tokens):
        self.tokens = list(tokens)
        self.tokens.append(Token("EOF", "EOF", -1, -1))
        self.current = 0
        self.errors = []

    def parse(self):
        raiz = ASTNode("Program")

        while not self.is_at_end():
            try:
                raiz.add(self.declaration())
            except ParseError:
                self.synchronize()

        return raiz

    # Recuperacao panic mode:
    # ao encontrar erro, ignora tokens ate achar ';', '}' ou inicio provavel
    # de um novo comando/declaracao. Assim a analise continua e mostra varios erros.
    def synchronize(self):
        while not self.is_at_end():
            if self.previous().value == ";":
                return
            if self.peek().value in {"}"}:
                return
            if self.peek().value in self.STATEMENT_STARTERS:
                return
            self.advance()

    def declaration(self):
        if self.peek().type == "MISMATCH":
            token = self.advance()
            self.error(token, f"Token invalido '{token.value}'")
            raise ParseError()

        if self.is_type_keyword():
            return self.type_declaration()

        return self.statement()

    def type_declaration(self):
        type_token = self.advance()
        name = self.consume("ID", "Esperado identificador apos tipo")

        if self.match_value("("):
            return self.function_declaration(type_token, name)

        return self.variable_declaration(type_token, name, consume_semicolon=True)

    def function_declaration(self, type_token, name):
        params = ASTNode("Params")

        if not self.check_value(")"):
            while True:
                param_type = self.consume_type("Esperado tipo do parametro")
                param_name = self.consume("ID", "Esperado nome do parametro")
                params.add(ASTNode("Param", param_name.value, [
                    ASTNode("Type", param_type.value, line=param_type.line, column=param_type.column)
                ], param_name.line, param_name.column))

                if not self.match_value(","):
                    break

        self.consume_value(")", "Esperado ')' apos parametros")
        body = self.block()

        return ASTNode("FunctionDecl", name.value, [
            ASTNode("ReturnType", type_token.value, line=type_token.line, column=type_token.column),
            params,
            body
        ], name.line, name.column)

    def variable_declaration(self, type_token, first_name, consume_semicolon):
        decl = ASTNode("VarDecl", type_token.value, line=type_token.line, column=type_token.column)
        name = first_name

        while True:
            var = ASTNode("Var", name.value, line=name.line, column=name.column)
            if self.match("ASSIGN"):
                var.add(self.expression())
            decl.add(var)

            if not self.match_value(","):
                break

            name = self.consume("ID", "Esperado identificador apos ','")

        if consume_semicolon:
            self.consume_value(";", "Esperado ';' apos declaracao de variavel")

        return decl

    def statement(self):
        if self.match_value("{"):
            return self.finish_block()
        if self.match_keyword("if"):
            return self.if_statement()
        if self.match_keyword("while"):
            return self.while_statement()
        if self.match_keyword("for"):
            return self.for_statement()
        if self.match_keyword("return"):
            return self.return_statement()
        if self.match_keyword("break"):
            token = self.previous()
            self.consume_value(";", "Esperado ';' apos break")
            return ASTNode("Break", line=token.line, column=token.column)
        if self.match_keyword("continue"):
            token = self.previous()
            self.consume_value(";", "Esperado ';' apos continue")
            return ASTNode("Continue", line=token.line, column=token.column)

        return self.expression_statement()

    def block(self):
        self.consume_value("{", "Esperado '{' para iniciar bloco")
        return self.finish_block()

    def finish_block(self):
        bloco = ASTNode("Block")

        while not self.check_value("}") and not self.is_at_end():
            try:
                bloco.add(self.declaration())
            except ParseError:
                self.synchronize()
                if self.check_value("}"):
                    break

        self.consume_value("}", "Esperado '}' para fechar bloco")
        return bloco

    def if_statement(self):
        token = self.previous()
        self.consume_value("(", "Esperado '(' apos if")
        condition = self.expression()
        self.consume_value(")", "Esperado ')' apos condicao")
        then_branch = self.statement()
        else_branch = self.statement() if self.match_keyword("else") else None

        return ASTNode("If", line=token.line, column=token.column).add(condition).add(then_branch).add(else_branch)

    def while_statement(self):
        token = self.previous()
        self.consume_value("(", "Esperado '(' apos while")
        condition = self.expression()
        self.consume_value(")", "Esperado ')' apos condicao")
        body = self.statement()

        return ASTNode("While", line=token.line, column=token.column).add(condition).add(body)

    def for_statement(self):
        token = self.previous()
        self.consume_value("(", "Esperado '(' apos for")

        if self.match_value(";"):
            init = None
        elif self.is_type_keyword():
            type_token = self.advance()
            name = self.consume("ID", "Esperado identificador na declaracao do for")
            init = self.variable_declaration(type_token, name, consume_semicolon=True)
        else:
            init = self.expression()
            self.consume_value(";", "Esperado ';' apos inicializacao do for")

        condition = None if self.check_value(";") else self.expression()
        self.consume_value(";", "Esperado ';' apos condicao do for")

        update = None if self.check_value(")") else self.expression()
        self.consume_value(")", "Esperado ')' apos for")

        body = self.statement()
        return ASTNode("For", line=token.line, column=token.column).add(init).add(condition).add(update).add(body)

    def return_statement(self):
        token = self.previous()
        expr = None if self.check_value(";") else self.expression()
        self.consume_value(";", "Esperado ';' apos return")
        return ASTNode("Return", line=token.line, column=token.column).add(expr)

    def expression_statement(self):
        expr = self.expression()
        self.consume_value(";", "Esperado ';' apos expressao")
        return ASTNode("ExprStmt").add(expr)

    def expression(self):
        return self.assignment()

    def assignment(self):
        expr = self.logic_or()

        if self.match("ASSIGN"):
            equals = self.previous()
            value = self.assignment()

            if expr.kind == "Identifier":
                return ASTNode("Assign", expr.value, [value], equals.line, equals.column)

            self.error(equals, "Destino invalido para atribuicao")
            raise ParseError()

        return expr

    def logic_or(self):
        return self.binary_left(self.logic_and, {"||"})

    def logic_and(self):
        return self.binary_left(self.equality, {"&&"})

    def equality(self):
        return self.binary_left(self.comparison, {"==", "!="})

    def comparison(self):
        return self.binary_left(self.term, {">", "<", ">=", "<="})

    def term(self):
        return self.binary_left(self.factor, {"+", "-", "%"})

    def factor(self):
        return self.binary_left(self.unary, {"*", "/"})

    def unary(self):
        if self.match_value("!", "-"):
            op = self.previous()
            right = self.unary()
            return ASTNode("UnaryOp", op.value, [right], op.line, op.column)

        return self.primary()

    def primary(self):
        if self.match("INT", "FLOAT", "STRING", "CHAR"):
            token = self.previous()
            return ASTNode("Literal", token.value, line=token.line, column=token.column)

        if self.match("ID"):
            token = self.previous()

            if self.match_value("("):
                call = ASTNode("Call", token.value, line=token.line, column=token.column)
                if not self.check_value(")"):
                    while True:
                        call.add(self.expression())
                        if not self.match_value(","):
                            break
                self.consume_value(")", "Esperado ')' apos argumentos")
                return call

            if self.match("OP_INC_DEC"):
                op = self.previous()
                return ASTNode("PostfixOp", op.value, [
                    ASTNode("Identifier", token.value, line=token.line, column=token.column)
                ], op.line, op.column)

            return ASTNode("Identifier", token.value, line=token.line, column=token.column)

        if self.match("OP_INC_DEC"):
            op = self.previous()
            name = self.consume("ID", "Esperado identificador apos incremento/decremento")
            return ASTNode("PrefixOp", op.value, [
                ASTNode("Identifier", name.value, line=name.line, column=name.column)
            ], op.line, op.column)

        if self.match_value("("):
            expr = self.expression()
            self.consume_value(")", "Esperado ')' apos expressao")
            return expr

        token = self.peek()
        self.error(token, f"Expressao esperada antes de '{token.value}'")
        raise ParseError()

    def binary_left(self, next_rule, operators):
        expr = next_rule()

        while self.peek().value in operators:
            op = self.advance()
            right = next_rule()
            expr = ASTNode("BinaryOp", op.value, [expr, right], op.line, op.column)

        return expr

    def match(self, *types):
        if self.peek().type in types:
            self.advance()
            return True
        return False

    def match_value(self, *values):
        if self.peek().value in values:
            self.advance()
            return True
        return False

    def match_keyword(self, value):
        if self.peek().type == "KEYWORD" and self.peek().value == value:
            self.advance()
            return True
        return False

    def consume(self, type_, message):
        if self.peek().type == type_:
            return self.advance()

        self.error(self.peek(), message)
        raise ParseError()

    def consume_value(self, value, message):
        if self.peek().value == value:
            return self.advance()

        self.error(self.peek(), message)
        raise ParseError()

    def consume_type(self, message):
        if self.is_type_keyword():
            return self.advance()

        self.error(self.peek(), message)
        raise ParseError()

    def is_type_keyword(self):
        return self.peek().type == "KEYWORD" and self.peek().value in self.TYPES

    def check_value(self, value):
        return self.peek().value == value

    def advance(self):
        if not self.is_at_end():
            self.current += 1
        return self.previous()

    def is_at_end(self):
        return self.peek().type == "EOF"

    def peek(self):
        return self.tokens[self.current]

    def previous(self):
        return self.tokens[self.current - 1]

    def error(self, token, message):
        local = "fim do arquivo" if token.type == "EOF" else f"linha {token.line}, coluna {token.column}"
        self.errors.append(f"Erro Sintatico em {local}: {message}")


class SemanticAnalyzer:
    NUMERIC = {"int", "float", "char"}
    INTEGER = {"int", "char"}
    OPERATIONS = {
        "+ - * /": "numerico x numerico -> numerico",
        "%": "inteiro x inteiro -> int",
        "> < >= <=": "numerico x numerico -> bool",
        "== !=": "tipos compativeis -> bool",
        "&& ||": "bool x bool -> bool",
        "!": "bool -> bool",
        "- unario": "numerico -> numerico",
        "= atribuicao": "tipo compativel com destino",
        "++ --": "variavel numerica -> mesmo tipo",
    }

    def __init__(self, ast):
        self.errors = []
        self.scopes = [{}]
        self.scope_names = ["global"]
        self.symbols = []
        self.current_return = None
        self.loop = 0
        self.blocks = 0
        self.ast = ast

    def analyze(self):
        for child in self.ast.children:
            if child.kind == "FunctionDecl":
                return_type = child.children[0].value
                self.declare(child.value, return_type, "funcao", child, self.params(child.children[1]))

        for child in self.ast.children:
            self.visit(child)

        return self.errors

    def visit(self, node):
        if node is None:
            return

        kind = node.kind

        if kind == "FunctionDecl":
            old_return = self.current_return
            self.current_return = node.children[0].value
            self.push(f"funcao {node.value}")
            for type_, name in self.params(node.children[1]):
                self.declare(name, type_, "parametro", node)
            self.visit(node.children[2])
            self.pop()
            self.current_return = old_return
            return

        if kind == "Block":
            self.blocks += 1
            self.push(f"bloco {self.blocks}")
            for child in node.children:
                self.visit(child)
            self.pop()
            return

        if kind == "VarDecl":
            if node.value == "void":
                self.error(node, "Variavel nao pode ter tipo void")
            for var in node.children:
                self.declare(var.value, node.value, "variavel", var)
                if var.children:
                    received = self.expr(var.children[0])
                    if not self.compatible(node.value, received):
                        self.error(var, f"Tipo incompativel na inicializacao de '{var.value}': esperado {node.value}, recebido {received}")
            return

        if kind == "ExprStmt":
            self.expr(node.children[0])
            return

        if kind == "If":
            self.condition(node.children[0], "if")
            for child in node.children[1:]:
                self.visit(child)
            return

        if kind == "While":
            self.condition(node.children[0], "while")
            self.loop += 1
            self.visit(node.children[1])
            self.loop -= 1
            return

        if kind == "For":
            self.push("for")
            for part in node.children[:-1]:
                self.visit(part) if part.kind == "VarDecl" else self.expr(part)
            self.loop += 1
            if node.children:
                self.visit(node.children[-1])
            self.loop -= 1
            self.pop()
            return

        if kind == "Return":
            received = "void" if not node.children else self.expr(node.children[0])
            if self.current_return is None:
                self.error(node, "Return fora de funcao")
            elif self.current_return == "void" and received != "void":
                self.error(node, "Funcao void nao deve retornar valor")
            elif self.current_return != "void" and received == "void":
                self.error(node, f"Funcao deve retornar valor do tipo {self.current_return}")
            elif not self.compatible(self.current_return, received):
                self.error(node, f"Tipo de retorno incompativel: esperado {self.current_return}, recebido {received}")
            return

        if kind in {"Break", "Continue"} and self.loop == 0:
            self.error(node, f"{kind} usado fora de laco")
            return

        for child in node.children:
            self.visit(child)

    def expr(self, node):
        if node is None:
            return "void"

        kind = node.kind

        if kind == "Literal":
            return self.literal_type(node.value)

        if kind == "Identifier":
            symbol = self.resolve(node.value, node)
            return symbol.type if symbol else "erro"

        if kind == "Assign":
            symbol = self.resolve(node.value, node)
            received = self.expr(node.children[0])
            if symbol and symbol.category == "funcao":
                self.error(node, f"'{node.value}' e uma funcao e nao pode receber atribuicao")
                return "erro"
            if symbol and not self.compatible(symbol.type, received):
                self.error(node, f"Tipo incompativel na atribuicao de '{node.value}': esperado {symbol.type}, recebido {received}")
                return "erro"
            return symbol.type if symbol else "erro"

        if kind == "Call":
            symbol = self.resolve(node.value, node)
            if not symbol:
                return "erro"
            if symbol.category != "funcao":
                self.error(node, f"'{node.value}' nao e uma funcao")
                return "erro"
            args = [self.expr(arg) for arg in node.children]
            if len(args) != len(symbol.params):
                self.error(node, f"Funcao '{node.value}' espera {len(symbol.params)} argumento(s), mas recebeu {len(args)}")
                return symbol.type
            for index, ((expected, _), received) in enumerate(zip(symbol.params, args), start=1):
                if not self.compatible(expected, received):
                    self.error(node, f"Argumento {index} de '{node.value}' deve ser {expected}, recebido {received}")
            return symbol.type

        if kind in {"PrefixOp", "PostfixOp"}:
            symbol = self.resolve(node.children[0].value, node.children[0])
            if symbol and symbol.type not in self.NUMERIC:
                self.error(node, f"Operador '{node.value}' exige variavel numerica")
                return "erro"
            return symbol.type if symbol else "erro"

        if kind == "UnaryOp":
            right = self.expr(node.children[0])
            if right == "erro":
                return "erro"
            if node.value == "!" and right == "bool":
                return "bool"
            if node.value == "-" and right in self.NUMERIC:
                return "float" if right == "float" else "int"
            self.error(node, f"Operador '{node.value}' usado com tipo invalido")
            return "erro"

        if kind == "BinaryOp":
            left = self.expr(node.children[0])
            right = self.expr(node.children[1])
            op = node.value
            if "erro" in {left, right}:
                return "erro"
            if op in {"+", "-", "*", "/"} and left in self.NUMERIC and right in self.NUMERIC:
                return "float" if "float" in {left, right} else "int"
            if op == "%" and left in self.INTEGER and right in self.INTEGER:
                return "int"
            if op in {">", "<", ">=", "<="} and left in self.NUMERIC and right in self.NUMERIC:
                return "bool"
            if op in {"==", "!="} and (self.compatible(left, right) or self.compatible(right, left)):
                return "bool"
            if op in {"&&", "||"} and left == right == "bool":
                return "bool"
            self.error(node, f"Operador '{op}' usado com tipos incompativeis")
            return "erro"

        return "erro"

    def condition(self, node, command):
        type_ = self.expr(node)
        if type_ not in self.NUMERIC | {"bool", "erro"}:
            self.error(node, f"Condicao do {command} deve ser bool ou numerica")

    def params(self, node):
        return [(param.children[0].value, param.value) for param in node.children]

    def declare(self, name, type_, category, node, params=None):
        current_scope = self.scopes[-1]
        if name in current_scope:
            self.error(node, f"Identificador '{name}' ja declarado neste escopo")
            return None

        symbol = Symbol(name, type_, category, self.scope_names[-1], params or [])
        current_scope[name] = symbol
        self.symbols.append(symbol)
        return symbol

    def resolve(self, name, node):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]

        self.error(node, f"Identificador '{name}' nao declarado")
        return None

    def push(self, name):
        self.scopes.append({})
        self.scope_names.append(name)

    def pop(self):
        self.scopes.pop()
        self.scope_names.pop()

    def literal_type(self, value):
        text = str(value)
        if text.startswith('"') and text.endswith('"'):
            return "string"
        if text.startswith("'") and text.endswith("'"):
            return "char"
        if text in {"true", "false"}:
            return "bool"
        if "." in text:
            return "float"
        return "int"

    def compatible(self, target, source):
        if "erro" in {target, source}:
            return True
        if target == source:
            return True
        if target == "float" and source in self.NUMERIC:
            return True
        if target == "int" and source == "char":
            return True
        return False

    def error(self, node, message):
        local = "local desconhecido"
        if node and node.line is not None:
            local = f"linha {node.line}, coluna {node.column}"
        self.errors.append(f"Erro Semantico em {local}: {message}")

    def format_symbol_table(self):
        if not self.symbols:
            return "(vazia)"

        lines = [f"{'ESCOPO':<15} | {'NOME':<15} | {'CATEGORIA':<10} | {'TIPO':<8} | PARAMETROS"]
        lines.append("-" * 75)

        for symbol in self.symbols:
            params = ", ".join(f"{type_} {name}" for type_, name in symbol.params) or "-"
            lines.append(
                f"{symbol.scope:<15} | {symbol.name:<15} | {symbol.category:<10} | "
                f"{symbol.type:<8} | {params}"
            )

        return "\n".join(lines)

    def format_operation_table(self):
        lines = [f"{'OPERACAO':<15} | REGRA"]
        lines.append("-" * 55)

        for operation, rule in self.OPERATIONS.items():
            lines.append(f"{operation:<15} | {rule}")

        return "\n".join(lines)


def analisar_arquivo(caminho):
    with open(caminho, "r", encoding="utf-8") as arquivo:
        codigo = arquivo.read()

    lexer = Lexer(codigo)
    parser = Parser(lexer.tokenize())
    ast = parser.parse()

    if parser.errors:
        print("ERRO: codigo sintaticamente incorreto")
        for erro in parser.errors:
            print(erro)
    else:
        print("SUCESSO: codigo sintaticamente correto")
        semantic = SemanticAnalyzer(ast)
        semantic_errors = semantic.analyze()

        print("\nTabela de simbolos:")
        print(semantic.format_symbol_table())

        print("\nTabela de tipos e operacoes:")
        print(semantic.format_operation_table())

        if semantic_errors:
            print("\nERRO: codigo semanticamente incorreto")
            for erro in semantic_errors:
                print(erro)
        else:
            print("\nSUCESSO: codigo semanticamente correto")

    print("\nAST:")
    print(ast.pretty())
    return ast


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python analisador_sintatico.py <arquivo.c>")
        sys.exit(1)

    analisar_arquivo(sys.argv[1])
