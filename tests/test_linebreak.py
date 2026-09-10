"""Regras de quebra de linha.

Estes testes rodam sem rede, sem ffmpeg e sem display -- e a parte do projeto
que define a qualidade da legenda, entao e onde a cobertura precisa ser densa.
"""
from __future__ import annotations

from subtitler.core.linebreak import PROIBIDO, best_split, normalizar, peso_sintatico, wrap


def test_cabe_em_uma_linha_nao_quebra():
    """Legenda de uma linha e lida mais rapido; nao inventar segunda linha."""
    assert wrap("Bom dia, pessoal!") == ["Bom dia, pessoal!"]


def test_quebra_depois_da_virgula():
    """A virgula acompanha a respiracao de quem fala."""
    linhas = wrap("Ele disse que nao ia dar certo, mas a gente foi mesmo assim")
    assert linhas is not None
    assert linhas[0].endswith(",")
    assert linhas == ["Ele disse que nao ia dar certo,", "mas a gente foi mesmo assim"]


def test_nunca_separa_preposicao_do_termo():
    """"de | manha" obriga o olho a voltar."""
    assert peso_sintatico("de", "manha") == PROIBIDO
    assert peso_sintatico("para", "casa") == PROIBIDO
    assert peso_sintatico("com", "cuidado") == PROIBIDO


def test_nunca_separa_artigo_do_substantivo():
    assert peso_sintatico("a", "casa") == PROIBIDO
    assert peso_sintatico("uma", "hora") == PROIBIDO


def test_nunca_separa_simbolo_do_valor():
    assert peso_sintatico("R$", "1.500") == PROIBIDO
    assert peso_sintatico("US$", "20") == PROIBIDO


def test_nunca_separa_numero_da_unidade():
    assert peso_sintatico("10", "km") == PROIBIDO
    assert peso_sintatico("30", "fps") == PROIBIDO


def test_nunca_separa_nome_proprio_composto():
    """"Joao | da Silva" quebra o nome ao meio."""
    assert peso_sintatico("Joao", "da") == PROIBIDO


def test_ponto_final_e_o_melhor_corte():
    assert peso_sintatico("certo.", "Depois") == 0.0
    assert peso_sintatico("certo,", "depois") == 1.0
    assert peso_sintatico("certo", "mas") == 2.0
    # espaco comum custa mais que qualquer fronteira sintatica
    assert peso_sintatico("casa", "azul") == 6.0


def test_nenhuma_linha_passa_do_limite():
    texto = (
        "Esse foi sem duvida o momento mais improvavel da gameplay inteira "
        "e ninguem esperava aquilo acontecer bem ali"
    )
    linhas = wrap(texto, max_chars=42)
    if linhas is not None:
        assert all(len(l) <= 42 for l in linhas)
        assert len(linhas) <= 2


def test_prefere_linha_de_cima_menor():
    """Empate resolve bottom-heavy: cobre menos imagem.

    O texto precisa passar de 42 caracteres, senao cabe numa linha so e nao ha
    empate para desempatar -- foi assim que este teste nasceu errado.
    """
    linhas = wrap("um dois tres quatro cinco seis sete oito nove dez")
    assert linhas is not None and len(linhas) == 2
    assert len(linhas[0]) <= len(linhas[1])


def test_devolve_none_quando_nao_cabe_em_duas_linhas():
    """O sinal para quem chamou dividir a legenda no TEMPO, nao gerar 3 linhas."""
    texto = " ".join(["palavra"] * 40)
    assert wrap(texto, max_chars=42, max_lines=2) is None


def test_normalizar_cola_pontuacao_e_colapsa_espacos():
    assert normalizar("ola   ,  tudo bem ?") == "ola, tudo bem?"


def test_best_split_nao_corta_no_meio_da_palavra():
    """O corte e sempre num espaco -- as duas linhas juntas reconstroem o texto."""
    texto = "A gente conseguiu terminar aquela fase dificil ontem a noite"
    corte = best_split(texto)
    assert corte is not None
    palavras = normalizar(texto).split(" ")
    assert " ".join(palavras[:corte]) + " " + " ".join(palavras[corte:]) == normalizar(texto)


def test_texto_vazio_devolve_none():
    assert wrap("") is None
    assert wrap("   ") is None
