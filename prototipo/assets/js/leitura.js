/* Leitura em voz alta das páginas de trilha.
   Usa apenas window.speechSynthesis e SpeechSynthesisUtterance.
   O conteúdo da página permanece disponível sem JavaScript. */

(function () {
    "use strict";

    var TEM_SINTESE = typeof window !== "undefined" &&
        "speechSynthesis" in window &&
        "SpeechSynthesisUtterance" in window;

    var sintese = TEM_SINTESE ? window.speechSynthesis : null;
    var vozPtBr = null;
    var geracao = 0;
    var botaoAtivo = null;

    function iniciar() {
        var botoes = document.querySelectorAll("[data-ouvir-painel]");

        if (!TEM_SINTESE) {
            for (var i = 0; i < botoes.length; i++) {
                botoes[i].disabled = true;
                informarEstado(botoes[i],
                    "Leitura em voz alta não está disponível neste navegador.");
            }
            return;
        }

        if (typeof sintese.addEventListener === "function") {
            sintese.addEventListener("voiceschanged", escolherVoz);
        } else if ("onvoiceschanged" in sintese) {
            sintese.onvoiceschanged = escolherVoz;
        }
        escolherVoz();

        for (var j = 0; j < botoes.length; j++) {
            prepararBotao(botoes[j]);
        }

        window.addEventListener("pagehide", pararLeitura);
    }

    /* Escolhe voz em português; aceita carregamento tardio da lista. */
    function escolherVoz() {
        var vozes = sintese.getVoices();
        vozPtBr = null;
        for (var i = 0; i < vozes.length; i++) {
            var idioma = (vozes[i].lang || "").toLowerCase().replace("_", "-");
            if (idioma.indexOf("pt-br") !== -1) {
                vozPtBr = vozes[i];
                return;
            }
        }
        for (var k = 0; k < vozes.length; k++) {
            var idiomaGeral = (vozes[k].lang || "").toLowerCase();
            if (idiomaGeral.indexOf("pt") !== -1) {
                vozPtBr = vozes[k];
                return;
            }
        }
        /* Sem voz em português localizada: mantém null e o motor decide.
           Nenhuma voz de outro idioma é selecionada deliberadamente. */
    }

    function nomeDoBotao(botao) {
        return botao.getAttribute("data-ouvir-nome") || "conteúdo do painel";
    }

    function informarEstado(botao, texto) {
        var area = botao.closest(".painel__lateral");
        var estado = area ? area.querySelector(".ouvir__estado") : null;
        if (estado) {
            estado.textContent = texto;
        }
    }

    function marcarLendo(botao) {
        botao.setAttribute("aria-label", "Parar leitura: " + nomeDoBotao(botao));
        botao.classList.add("ouvir--lendo");
    }

    function restaurarBotao(botao) {
        botao.setAttribute("aria-label", "Ouvir conteúdo: " + nomeDoBotao(botao));
        botao.classList.remove("ouvir--lendo");
    }

    function prepararBotao(botao) {
        restaurarBotao(botao);

        botao.addEventListener("click", function () {
            if (botao === botaoAtivo) {
                informarEstado(botao, "Leitura interrompida.");
                pararLeitura();
                return;
            }
            pararLeitura();

            var minhaGeracao = geracao + 1;
            geracao = minhaGeracao;
            botaoAtivo = botao;
            marcarLendo(botao);
            informarEstado(botao, "Leitura em andamento.");

            /* Pequena espera após cancel(): alguns navegadores descartam
               a nova fala quando ela começa imediatamente após um
               cancelamento. O token de geração impede que esta espera
               retome uma leitura que o usuário já interrompeu. */
            window.setTimeout(function () {
                if (minhaGeracao !== geracao) {
                    return;
                }
                iniciarSequencia(botao, minhaGeracao);
            }, 120);
        });
    }

    /* Interrompe qualquer leitura e invalida callbacks pendentes. */
    function pararLeitura() {
        geracao = geracao + 1;
        if (botaoAtivo) {
            restaurarBotao(botaoAtivo);
            botaoAtivo = null;
        }
        try {
            sintese.cancel();
        } catch (erro) {
            /* Alguns motores lançam exceção ao cancelar sem fala ativa. */
        }
    }

    /* Listas são lidas como um único trecho, com itens separados
       por vírgulas, para manter a narração fluida e ordenada.
       Linhas de tabela são lidas célula a célula, na ordem do
       documento, com pausas entre as células. */
    function textoDoElemento(elemento) {
        var nome = elemento.tagName;
        if (nome === "UL" || nome === "OL") {
            var itens = elemento.querySelectorAll("li");
            var partes = [];
            for (var i = 0; i < itens.length; i++) {
                var item = (itens[i].textContent || "")
                    .replace(/\s+/g, " ")
                    .trim();
                if (item) {
                    partes.push(item);
                }
            }
            return partes.join(", ") + (partes.length ? "." : "");
        }
        if (nome === "TR") {
            var celulas = elemento.querySelectorAll("th, td");
            var valores = [];
            for (var c = 0; c < celulas.length; c++) {
                var celula = (celulas[c].textContent || "")
                    .replace(/\s+/g, " ")
                    .trim();
                if (celula) {
                    valores.push(celula);
                }
            }
            return valores.join(". ") + (valores.length ? "." : "");
        }
        return (elemento.textContent || "")
            .replace(/\s+/g, " ")
            .trim();
    }

    function iniciarSequencia(botao, minhaGeracao) {
        var painel = document.querySelector(
            botao.getAttribute("data-ouvir-painel") || ""
        );
        var trechos = [];
        if (painel) {
            var elementos = painel.querySelectorAll("[data-ler]");
            for (var i = 0; i < elementos.length; i++) {
                var texto = textoDoElemento(elementos[i]);
                if (texto) {
                    trechos.push(texto);
                }
            }
        }

        if (!trechos.length) {
            informarEstado(botao, "Não há conteúdo de leitura neste painel.");
            restaurarBotao(botao);
            botaoAtivo = null;
            return;
        }

        falar(botao, trechos, 0, minhaGeracao);
    }

    /* Lê trecho por trecho, na ordem. Callbacks antigos não retomam
       uma leitura que já foi interrompida ou substituída. */
    function falar(botao, trechos, indice, minhaGeracao) {
        if (minhaGeracao !== geracao) {
            return;
        }
        if (indice >= trechos.length) {
            if (botaoAtivo === botao) {
                informarEstado(botao, "Leitura concluída.");
                restaurarBotao(botao);
                botaoAtivo = null;
            }
            return;
        }

        var fala = new SpeechSynthesisUtterance(trechos[indice]);
        fala.lang = "pt-BR";
        if (vozPtBr) {
            fala.voice = vozPtBr;
        }

        fala.onend = function () {
            if (minhaGeracao !== geracao) {
                return;
            }
            falar(botao, trechos, indice + 1, minhaGeracao);
        };

        fala.onerror = function () {
            if (minhaGeracao !== geracao) {
                return;
            }
            if (botaoAtivo === botao) {
                informarEstado(botao,
                    "Não foi possível concluir a leitura neste navegador.");
                restaurarBotao(botao);
                botaoAtivo = null;
            }
        };

        sintese.speak(fala);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciar);
    } else {
        iniciar();
    }
})();
