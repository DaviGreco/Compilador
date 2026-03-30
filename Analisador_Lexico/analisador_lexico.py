import re
import sys

class Token:
    def __init__(self, type_, value, line, column):
        self.type = type_
        self.value = value
        self.line = line
        self.column = column

    def __repr__(self):
        return f"Token(tipo='{self.type}', valor={repr(self.value)}, linha={self.line}, col={self.column})"

class Lexer:
    
    # Palavras reservadas
    KEYWORDS = {
        'int', 'float', 'char', 'void', 'return', 'if', 'else', 'while', 
        'for', 'break', 'continue', 'printf', 'bool', 'string'
    }

    # Tabela de códigos numéricos para cada classe
    TOKEN_CODES = {
        'KEYWORD': 1,
        'ID': 2,
        'INT': 3,
        'FLOAT': 4,
        'STRING': 5,
        'CHAR': 6,
        'OP_INC_DEC': 7,
        'OP_MATH': 8,
        'OP_REL': 9,
        'OP_LOGIC': 10,
        'ASSIGN': 11,
        'PUNCTUATION': 12,
        'MISMATCH': 99
    }

    RULES = [
        ('COMMENT_MULTI', r'/\*[\s\S]*?\*/'),  # /* Comentários longos */
        ('COMMENT_SINGLE', r'//.*'),           # // Comentários curtos
        ('CHAR', r"'(?:\\.|[^'\\])'"),         # Letras isoladas: 'a', '\n'
        ('STRING', r'"[^"\\]*(\\.[^"\\]*)*"'), # Textos: "olá mundo"
        ('FLOAT', r'\d+\.\d+'),                # Números decimais: 3.14
        ('INT', r'\d+'),                       # Números inteiros: 42
        ('ID', r'[a-zA-Z_]\w*'),               # Nomes de variáveis e funções
        ('OP_INC_DEC', r'\+\+|--'),            # Incremento e decremento: ++, --
        ('OP_REL', r'==|!=|<=|>=|<|>'),        # Operadores de comparação: ==, !=, >=
        ('OP_LOGIC', r'&&|\|\||!'),            # Operadores lógicos: &&, ||, !
        ('OP_MATH', r'\+|-|\*|/|%'),           # Matemática básica: +, -, *, /, %
        ('ASSIGN', r'='),                      # Sinal de igual
        ('PUNCTUATION', r'[(){}\[\];,]'),      # Chaves, parênteses, vírgulas, etc.
        ('WHITESPACE', r'[ \t]+'),             # Espaços e tabs (vamos ignorar depois)
        ('NEWLINE', r'\n'),                    # Quebra de linha
        ('MISMATCH', r'.'),                    # Pega qualquer coisa que sobrou (pra acusar erro)
    ]

    def __init__(self, code):
        self.code = code
        self.regex = '|'.join(f'(?P<{name}>{pattern})' for name, pattern in self.RULES)
        self.compiled_regex = re.compile(self.regex)

    def tokenize(self):
        line_num = 1
        line_start = 0

        for match in self.compiled_regex.finditer(self.code):
            type_ = match.lastgroup
            value = match.group(type_)
            column = match.start() - line_start + 1

            if type_ == 'NEWLINE':
                line_num += 1
                line_start = match.end()
                continue
            
            elif type_ in ('WHITESPACE', 'COMMENT_SINGLE', 'COMMENT_MULTI'):
                if type_ == 'COMMENT_MULTI':
                    newlines = value.count('\n')
                    line_num += newlines
                    if newlines > 0:
                        line_start = match.end() - len(value.split('\n')[-1])
                continue
            
            elif type_ == 'ID':
                if value in self.KEYWORDS:
                    type_ = 'KEYWORD'
            
            elif type_ == 'MISMATCH':
                print(f"Erro Léxico: Caractere inesperado '{value}' na linha {line_num}, coluna {column}", file=sys.stderr)
                yield Token(type_, value, line_num, column)
                continue

            yield Token(type_, value, line_num, column)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Uso: python lexer.py <arquivo.c> [arquivo_saida.txt]")
        sys.exit(1)

    arquivo_entrada = sys.argv[1]
    
    arquivo_saida = sys.argv[2] if len(sys.argv) > 2 else "tabela_tokens.txt"

    try:
        with open(arquivo_entrada, 'r', encoding='utf-8') as f:
            codigo_c = f.read()
    except FileNotFoundError:
        print(f"Erro: O arquivo '{arquivo_entrada}' não foi encontrado.")
        sys.exit(1)
    except Exception as e:
        print(f"Erro ao ler o arquivo de entrada: {e}")
        sys.exit(1)

    lexer = Lexer(codigo_c)
    
    try:
        with open(arquivo_saida, 'w', encoding='utf-8') as fout:
            fout.write(f"{'COD':<5} | {'TOKEN':<20} | {'CLASSE':<15} | {'LINHA':<7} | {'COLUNA'}\n")
            fout.write("-" * 68 + "\n")

            for token in lexer.tokenize():
                cod = Lexer.TOKEN_CODES.get(token.type, 0) 
                
                linha_formatada = f"{cod:<5} | {repr(token.value):<20} | {token.type:<15} | {token.line:<7} | {token.column}\n"
                fout.write(linha_formatada)
                
        print(f"Sucesso! A análise foi concluída e a tabela foi salva em: '{arquivo_saida}'")
        
    except Exception as e:
        print(f"Erro ao salvar o arquivo de saída: {e}")
        sys.exit(1)