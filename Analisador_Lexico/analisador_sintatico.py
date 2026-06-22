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
    # Adicionado para propagar o tipo avaliado de baixo para cima na arvore
    expr_type: str = "void" 

    def add(self, child):
        if child is not None:
            self.children.append(child)
        return self

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

    # Constantes auxiliares para a analise semantica
    NUMERIC = {"int", "float", "char"}
    INTEGER = {"int", "char"}

    def __init__(self, tokens):
        self.tokens = list(tokens)
        self.tokens.append(Token("EOF", "EOF", -1, -1))
        self.current = 0
        self.errors = []
        
        # Estado do Analisador Semantico
        self.semantic_errors = []
        self.scopes = [{}]             # Pilha de dicionarios para escopos locais
        self.scope_names = ["global"]  # Rastreia o nome do escopo atual
        self.symbols = []              # Lista de todos os simbolos para impressao
        self.current_return = None     # Tipo de retorno da funcao atual
        self.loop_count = 0            # Contador para validar break/continue
        self.block_count = 0           # Identificador visual para blocos

    def parse(self):
        raiz = ASTNode("Program")

        while not self.is_at_end():
            try:
                raiz.add(self.declaration())
            except ParseError:
                self.synchronize()

        return raiz

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
        parsed_params = [] # Guarda os parametros para a tabela de simbolos

        if not self.check_value(")"):
            while True:
                param_type = self.consume_type("Esperado tipo do parametro")
                param_name = self.consume("ID", "Esperado nome do parametro")
                
                params.add(ASTNode("Param", param_name.value, [
                    ASTNode("Type", param_type.value, line=param_type.line, column=param_type.column)
                ], param_name.line, param_name.column))
                
                parsed_params.append((param_type.value, param_name.value))

                if not self.match_value(","):
                    break

        self.consume_value(")", "Esperado ')' apos parametros")
        
        # Semantica: Registra funcao antes de ler o corpo para permitir recursao
        self.declare_symbol(name.value, type_token.value, "funcao", name, parsed_params)
        
        old_return = self.current_return
        self.current_return = type_token.value
        
        # Semantica: Abre escopo da funcao e registra os parametros
        self.push_scope(f"funcao {name.value}")
        for p_type, p_name in parsed_params:
            self.declare_symbol(p_name, p_type, "parametro", name)

        # O corpo nao precisa criar um novo escopo, usa o que acabamos de abrir
        body = self.block(create_scope=False)

        # Semantica: Fecha escopo e limpa retorno
        self.pop_scope()
        self.current_return = old_return

        return ASTNode("FunctionDecl", name.value, [
            ASTNode("ReturnType", type_token.value, line=type_token.line, column=type_token.column),
            params,
            body
        ], name.line, name.column)

    def variable_declaration(self, type_token, first_name, consume_semicolon):
        # Semantica: variaveis nao podem ser void
        if type_token.value == "void":
            self.semantic_error(type_token, "Variavel nao pode ter tipo void")

        decl = ASTNode("VarDecl", type_token.value, line=type_token.line, column=type_token.column)
        name = first_name

        while True:
            # Semantica: Declara a variavel no escopo atual
            self.declare_symbol(name.value, type_token.value, "variavel", name)
            
            var = ASTNode("Var", name.value, line=name.line, column=name.column)
            
            if self.match("ASSIGN"):
                expr = self.expression()
                # Semantica: Verifica se o valor atribuido eh compativel com o tipo
                if not self.is_compatible(type_token.value, expr.expr_type):
                    self.semantic_error(name, f"Tipo incompativel na inicializacao de '{name.value}': esperado {type_token.value}, recebido {expr.expr_type}")
                var.add(expr)
                
            decl.add(var)

            if not self.match_value(","):
                break

            name = self.consume("ID", "Esperado identificador apos ','")

        if consume_semicolon:
            self.consume_value(";", "Esperado ';' apos declaracao de variavel")

        return decl

    def statement(self):
        if self.match_value("{"):
            return self.finish_block(create_scope=True)
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
            # Semantica: break deve estar dentro de um loop
            if self.loop_count == 0:
                self.semantic_error(token, "break usado fora de laco")
            return ASTNode("Break", line=token.line, column=token.column)
            
        if self.match_keyword("continue"):
            token = self.previous()
            self.consume_value(";", "Esperado ';' apos continue")
            # Semantica: continue deve estar dentro de um loop
            if self.loop_count == 0:
                self.semantic_error(token, "continue usado fora de laco")
            return ASTNode("Continue", line=token.line, column=token.column)

        return self.expression_statement()

    def block(self, create_scope=True):
        self.consume_value("{", "Esperado '{' para iniciar bloco")
        return self.finish_block(create_scope)

    def finish_block(self, create_scope=True):
        if create_scope:
            self.block_count += 1
            self.push_scope(f"bloco {self.block_count}")

        bloco = ASTNode("Block")

        while not self.check_value("}") and not self.is_at_end():
            try:
                bloco.add(self.declaration())
            except ParseError:
                self.synchronize()
                if self.check_value("}"):
                    break

        self.consume_value("}", "Esperado '}' para fechar bloco")
        
        if create_scope:
            self.pop_scope()
            
        return bloco

    def if_statement(self):
        token = self.previous()
        self.consume_value("(", "Esperado '(' apos if")
        condition = self.expression()
        self.check_condition_type(condition, "if")
        self.consume_value(")", "Esperado ')' apos condicao")
        
        then_branch = self.statement()
        else_branch = self.statement() if self.match_keyword("else") else None

        return ASTNode("If", line=token.line, column=token.column).add(condition).add(then_branch).add(else_branch)

    def while_statement(self):
        token = self.previous()
        self.consume_value("(", "Esperado '(' apos while")
        condition = self.expression()
        self.check_condition_type(condition, "while")
        self.consume_value(")", "Esperado ')' apos condicao")
        
        self.loop_count += 1
        body = self.statement()
        self.loop_count -= 1

        return ASTNode("While", line=token.line, column=token.column).add(condition).add(body)

    def for_statement(self):
        token = self.previous()
        self.consume_value("(", "Esperado '(' apos for")

        # Abre escopo para lidar com a variavel de inicializacao do for
        self.push_scope("for")

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
        if condition:
            self.check_condition_type(condition, "for")
        self.consume_value(";", "Esperado ';' apos condicao do for")

        update = None if self.check_value(")") else self.expression()
        self.consume_value(")", "Esperado ')' apos for")

        self.loop_count += 1
        body = self.statement()
        self.loop_count -= 1
        
        self.pop_scope()

        return ASTNode("For", line=token.line, column=token.column).add(init).add(condition).add(update).add(body)

    def return_statement(self):
        token = self.previous()
        expr = None if self.check_value(";") else self.expression()
        self.consume_value(";", "Esperado ';' apos return")
        
        # Semantica: Regras de retorno da funcao
        received = expr.expr_type if expr else "void"
        
        if self.current_return is None:
            self.semantic_error(token, "Return fora de funcao")
        elif self.current_return == "void" and received != "void":
            self.semantic_error(token, "Funcao void nao deve retornar valor")
        elif self.current_return != "void" and received == "void":
            self.semantic_error(token, f"Funcao deve retornar valor do tipo {self.current_return}")
        elif not self.is_compatible(self.current_return, received):
            self.semantic_error(token, f"Tipo de retorno incompativel: esperado {self.current_return}, recebido {received}")

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
                node = ASTNode("Assign", expr.value, [value], equals.line, equals.column)
                
                # Semantica: Validar atribuicao
                symbol = self.resolve_symbol(expr.value, equals)
                if symbol:
                    if symbol.category == "funcao":
                        self.semantic_error(equals, f"'{expr.value}' e uma funcao e nao pode receber atribuicao")
                        node.expr_type = "erro"
                    elif not self.is_compatible(symbol.type, value.expr_type):
                        self.semantic_error(equals, f"Tipo incompativel na atribuicao de '{expr.value}': esperado {symbol.type}, recebido {value.expr_type}")
                        node.expr_type = "erro"
                    else:
                        node.expr_type = symbol.type
                else:
                    node.expr_type = "erro"
                return node

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
            node = ASTNode("UnaryOp", op.value, [right], op.line, op.column)
            
            # Semantica: Tipagem de operadores unarios
            r_type = right.expr_type
            if r_type == "erro":
                node.expr_type = "erro"
            elif op.value == "!" and r_type == "bool":
                node.expr_type = "bool"
            elif op.value == "-" and r_type in self.NUMERIC:
                node.expr_type = "float" if r_type == "float" else "int"
            else:
                self.semantic_error(op, f"Operador '{op.value}' usado com tipo invalido")
                node.expr_type = "erro"
            return node

        return self.primary()

    def primary(self):
        if self.match("INT", "FLOAT", "STRING", "CHAR"):
            token = self.previous()
            node = ASTNode("Literal", token.value, line=token.line, column=token.column)
            node.expr_type = self.infer_literal_type(token.value)
            return node

        if self.match("ID"):
            token = self.previous()

            if self.match_value("("):
                call = ASTNode("Call", token.value, line=token.line, column=token.column)
                args_types = []
                
                if not self.check_value(")"):
                    while True:
                        arg_expr = self.expression()
                        call.add(arg_expr)
                        args_types.append(arg_expr.expr_type)
                        if not self.match_value(","):
                            break
                            
                self.consume_value(")", "Esperado ')' apos argumentos")
                
                # Semantica: Valida chamada de funcao e seus argumentos
                symbol = self.resolve_symbol(token.value, token)
                if not symbol:
                    call.expr_type = "erro"
                elif symbol.category != "funcao":
                    self.semantic_error(token, f"'{token.value}' nao e uma funcao")
                    call.expr_type = "erro"
                elif len(args_types) != len(symbol.params):
                    self.semantic_error(token, f"Funcao '{token.value}' espera {len(symbol.params)} argumento(s), mas recebeu {len(args_types)}")
                    call.expr_type = symbol.type
                else:
                    for index, ((expected, _), received) in enumerate(zip(symbol.params, args_types), start=1):
                        if not self.is_compatible(expected, received):
                            self.semantic_error(token, f"Argumento {index} de '{token.value}' deve ser {expected}, recebido {received}")
                    call.expr_type = symbol.type
                return call

            if self.match("OP_INC_DEC"):
                op = self.previous()
                node = ASTNode("PostfixOp", op.value, [
                    ASTNode("Identifier", token.value, line=token.line, column=token.column)
                ], op.line, op.column)
                
                # Semantica: Incremento pos-fixado exige numero
                symbol = self.resolve_symbol(token.value, token)
                if symbol and symbol.type not in self.NUMERIC:
                    self.semantic_error(op, f"Operador '{op.value}' exige variavel numerica")
                    node.expr_type = "erro"
                else:
                    node.expr_type = symbol.type if symbol else "erro"
                return node

            node = ASTNode("Identifier", token.value, line=token.line, column=token.column)
            symbol = self.resolve_symbol(token.value, token)
            node.expr_type = symbol.type if symbol else "erro"
            return node

        if self.match("OP_INC_DEC"):
            op = self.previous()
            name = self.consume("ID", "Esperado identificador apos incremento/decremento")
            node = ASTNode("PrefixOp", op.value, [
                ASTNode("Identifier", name.value, line=name.line, column=name.column)
            ], op.line, op.column)
            
            # Semantica: Incremento pre-fixado exige numero
            symbol = self.resolve_symbol(name.value, name)
            if symbol and symbol.type not in self.NUMERIC:
                self.semantic_error(op, f"Operador '{op.value}' exige variavel numerica")
                node.expr_type = "erro"
            else:
                node.expr_type = symbol.type if symbol else "erro"
            return node

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
            new_expr = ASTNode("BinaryOp", op.value, [expr, right], op.line, op.column)
            
            # Semantica: Define o tipo resultante baseado na operacao matematica/logica
            l_type = expr.expr_type
            r_type = right.expr_type
            
            if "erro" in {l_type, r_type}:
                new_expr.expr_type = "erro"
            elif op.value in {"+", "-", "*", "/"} and l_type in self.NUMERIC and r_type in self.NUMERIC:
                new_expr.expr_type = "float" if "float" in {l_type, r_type} else "int"
            elif op.value == "%" and l_type in self.INTEGER and r_type in self.INTEGER:
                new_expr.expr_type = "int"
            elif op.value in {">", "<", ">=", "<="} and l_type in self.NUMERIC and r_type in self.NUMERIC:
                new_expr.expr_type = "bool"
            elif op.value in {"==", "!="} and (self.is_compatible(l_type, r_type) or self.is_compatible(r_type, l_type)):
                new_expr.expr_type = "bool"
            elif op.value in {"&&", "||"} and l_type == r_type == "bool":
                new_expr.expr_type = "bool"
            else:
                self.semantic_error(op, f"Operador '{op.value}' usado com tipos incompativeis")
                new_expr.expr_type = "erro"
                
            expr = new_expr

        return expr

    # ==========================================================
    # UTILITARIOS SEMANTICOS
    # ==========================================================

    def declare_symbol(self, name, type_, category, token_node, params=None):
        current_scope = self.scopes[-1]
        if name in current_scope:
            self.semantic_error(token_node, f"Identificador '{name}' ja declarado neste escopo")
            return None

        symbol = Symbol(name, type_, category, self.scope_names[-1], params or [])
        current_scope[name] = symbol
        self.symbols.append(symbol)
        return symbol

    def resolve_symbol(self, name, token_node):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        self.semantic_error(token_node, f"Identificador '{name}' nao declarado")
        return None

    def push_scope(self, name):
        self.scopes.append({})
        self.scope_names.append(name)

    def pop_scope(self):
        self.scopes.pop()
        self.scope_names.pop()

    def check_condition_type(self, node, command):
        if node.expr_type not in self.NUMERIC | {"bool", "erro"}:
            self.semantic_error(node, f"Condicao do {command} deve ser bool ou numerica")

    def infer_literal_type(self, value):
        text = str(value)
        if text.startswith('"') and text.endswith('"'): return "string"
        if text.startswith("'") and text.endswith("'"): return "char"
        if text in {"true", "false"}: return "bool"
        if "." in text: return "float"
        return "int"

    def is_compatible(self, target, source):
        if "erro" in {target, source}: return True
        if target == source: return True
        if target == "float" and source in self.NUMERIC: return True
        if target == "int" and source == "char": return True
        return False

    def semantic_error(self, token_node, message):
        local = "local desconhecido"
        if token_node and token_node.line is not None:
            local = f"linha {token_node.line}, coluna {token_node.column}"
        self.semantic_errors.append(f"Erro Semantico em {local}: {message}")

    def format_symbol_table(self):
        if not self.symbols:
            return "(vazia)"

        lines = [f"{'ESCOPO':<15} | {'NOME':<15} | {'CATEGORIA':<10} | {'TIPO':<8} | PARAMETROS", "-" * 75]
        for symbol in self.symbols:
            params = ", ".join(f"{type_} {name}" for type_, name in symbol.params) or "-"
            lines.append(f"{symbol.scope:<15} | {symbol.name:<15} | {symbol.category:<10} | {symbol.type:<8} | {params}")
        return "\n".join(lines)

    # ==========================================================
    # UTILITARIOS SINTATICOS
    # ==========================================================

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

    print("\nTabela de simbolos:")
    print(parser.format_symbol_table())

    if parser.semantic_errors:
        print("\nERRO: codigo semanticamente incorreto")
        for erro in parser.semantic_errors:
            print(erro)
    elif not parser.errors:
        print("\nSUCESSO: codigo semanticamente correto")
    
    return ast


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python analisador.py <arquivo.c>")
        sys.exit(1)

    analisar_arquivo(sys.argv[1])