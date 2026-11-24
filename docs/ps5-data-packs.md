# PS5: os dados do jogo em pacotes com índice (design)

Estado: **implementado** (o padrão do builder). Escritor e leitor de referência: `ps5/builder/data_packs.py`; o passo 7
do builder: `ps5/builder/game_data.py`; o leitor do console: `host/ps5/pak_romfs.c`; testes: `tests/test_ps5_data_packs.py`
e `tests/test_pak_romfs.py` (este precisa de `gcc`: `bash scripts/docker/run_all.sh tests/test_pak_romfs.py`). A pasta
`Data/` solta continua como opção (`--data-folder`, ou "Game data as a folder" na janela do builder).

## 1. O problema

A pasta `Data/` tem **186.583 arquivos** (26,24 GB de conteúdo), e 142.663 deles têm menos de 128 KB. Num drive com
cluster grande, cada arquivo ocupa no mínimo um cluster:

| Onde a pasta `Data/` fica | Cluster | Espaço em disco |
|---|---|---|
| NTFS (C:, D:) | 4 KB | 24,9 GiB |
| exFAT 128 KB | 128 KB | 42,3 GiB |
| exFAT 256 KB (G:, E: de 931 GB) | 256 KB | **62,5 GiB** |

E levar 186 mil arquivos ao console por FTP leva horas: o custo é por arquivo, não por byte.

**Não é objetivo** comprimir nada: o conteúdo vai como está. O objetivo é ter **poucos arquivos grandes** e um **índice**
que diga onde está cada arquivo do jogo dentro deles.

### Por que isto não repete os problemas do `.nup`

A lentidão do leitor antigo (`host/ps5/nup_romfs.c`, removido) não vinha do tamanho do arquivo: um `pread` num arquivo de
25 GB custa o mesmo que num de 25 MB. Vinha de: (1) descomprimir por inteiro, na abertura, os 40.588 arquivos que o `.nup`
guardava em zstd, com um cache de 128 MiB que se renovava o tempo todo; (2) montar o índice no console a cada início
(ler 20-30 MB de metadados, percorrer a árvore, fazer a tabela hash); (3) procurar o pacote varrendo pastas e lendo 16 KB
de cada `.nup`. Aqui: nada comprimido, o índice vem pronto do builder, e o caminho dos arquivos é fixo.

## 2. Números (do índice do `.nup` do jogo, título v131072)

| | |
|---|---|
| Arquivos / pastas | 186.583 / 599 |
| Pacotes (um por pasta de topo, partes de até 4 GiB) | **53** (só `Tex` → 3 partes e `TerrainArc` → 2) |
| Tamanho dos pacotes (alinhamento de 16 B) | 24,44 GiB, **o mesmo em qualquer cluster** (sobra de alinhamento: 1 MB) |
| Maior arquivo / maior caminho | `Event/Movie/Dm_StaffCredit_0000.webm` 404 MB / 145 bytes |
| Nomes (só o último componente) | 6,7 MB |
| Índices na memória do console (seção 4) | ~23 MB: 50 índices de grupo (o maior, `TerrainArc`, 5,3 MB) |

Alinhamento de 4 KB custaria 456 MB a mais e só ajudaria a leitura direta (`O_DIRECT`), que o runtime não usa: fica 16 B.

## 3. O que vai na pasta do título

```
PPSA99198/
├── Data.idx                 o manifesto (< 10 KB): grupos, pacotes e onde está o índice de cada grupo; gravado por último
├── Data/
│   ├── AI.pak               grupo AI: seus arquivos e, no fim, o índice do grupo
│   ├── Tex.0.pak            grupo Tex, parte 0 (só dados)
│   ├── Tex.1.pak            parte 1 (só dados)
│   ├── Tex.2.pak            parte 2: dados e, no fim, o índice do grupo Tex inteiro
│   ├── TerrainArc.0.pak
│   ├── TerrainArc.1.pak     (com o índice do grupo TerrainArc)
│   └── ... 53 pacotes, 50 grupos
├── longshot_data.txt        o .nup de onde os dados vieram
└── eboot.bin, image.bin, ...
```

Um **grupo** é uma pasta de topo do romfs (`Tex`, `Model`, …; arquivos soltos na raiz, se houvesse, seriam o grupo `""`,
no pacote `Root.pak`). Cada grupo se descreve sozinho: o seu índice vai **dentro do seu último pacote**. O `Data.idx` é só
um manifesto pequeno, que diz quais grupos e pacotes existem e onde está e qual é o SHA-256 do índice de cada grupo.

Com `--data-folder` o builder faz como antes: `Data/` com os arquivos soltos, sem `Data.idx`.

## 4. Formatos (versão 2, little-endian)

### 4.1 Pacote `.pak`

```
0x00  "LSPK", u32 versão = 2, u32 número do pacote (no manifesto), u32 parte no seu grupo
0x10  16 bytes build_id        o mesmo do manifesto: um pacote de outro build é recusado
0x20  u64 tamanho dos dados
0x28  u64 onde começa o índice do grupo neste pacote (0 nas partes que não o têm)
0x30  u64 tamanho do índice do grupo
0x38  u32 número do grupo, u32 0
0x40  dados: os arquivos um após o outro, cada um começando num múltiplo de 16
      (na última parte do grupo) o índice do grupo, num múltiplo de 8, até o fim do arquivo
```

Conteúdo de cada arquivo: **exatamente** os bytes que `nx2/nup.py` extrai (o mesmo da pasta solta).

### 4.2 Índice de um grupo (no fim da última parte do grupo)

```
cabeçalho (0x80 = 128 B)
  0x00 "LSGI", u32 versão = 2, u32 número do grupo, u32 0
  0x10 16 bytes build_id
  0x20 u32 arquivos, u32 pastas, u32 partes, u32 capacidade da tabela hash (potência de 2)
  0x30 u64 offset (a partir do início do índice) e u64 tamanho de cada uma das 5 seções abaixo; cada uma num múltiplo de 8
seções
  pastas   { u32 nome, u32 tamanho do nome, u32 pai, u32 primeiro filho, u32 filhos }            (20 B)
  filhos   u32 cada: um nó (abaixo do nº de pastas é uma pasta, senão arquivo = nó - pastas), em ordem de nome
  arquivos { u32 nome, u32 tamanho do nome, u32 pasta, u16 parte, u16 flags, u64 offset nos dados da parte,
             u64 tamanho }                                                                     (32 B)
  hash     capacidade × { u64 hash do caminho, u32 nó, u32 0 }                                    (16 B)
  nomes    só o último componente de cada nome, UTF-8, sem terminador
```

- O nó 0 é a pasta do grupo (com o nome do grupo; pai = `0xffffffff`). Cada arquivo diz em que **parte** do grupo está.
- **Caminho** e **hash**: o caminho inteiro (`Tex/Algo/x.bntx.zs`), relativo à raiz, com `/`, sensível a maiúsculas;
  FNV-1a de 64 bits (0 trocado por 1). Uma colisão é desfeita comparando os nomes até a pasta do grupo.
- **Arquivo repetido** (flag 1): uma textura danificada aponta para a parte, o offset e o tamanho de uma inteira do
  mesmo tipo, da mesma pasta (logo, do mesmo grupo).

### 4.3 Manifesto `Data.idx`

```
cabeçalho (0x80 = 128 B)
  0x00 "LSMF", u32 versão = 2, u32 flags = 0, u32 0
  0x10 16 bytes build_id
  0x20 u32 grupos, u32 pacotes, u64 arquivos no total
  0x30 u64 offset e u64 tamanho de cada uma das 3 seções abaixo (cada uma num múltiplo de 8)
  0x60 SHA-256 de tudo o que vem depois do cabeçalho
seções
  grupos  { u32 nome, u32 tamanho do nome, u32 primeiro pacote, u32 partes, u32 arquivos, u32 0 }  (24 B), por nome
  pacotes { u32 nome do arquivo, u32 tamanho, u32 grupo, u32 parte, u64 tamanho do .pak,
            u64 onde está o índice do grupo, u64 tamanho do índice, 32 bytes SHA-256 do índice }   (72 B)
  nomes   UTF-8, sem terminador
```

As partes de um grupo vêm uma após a outra na lista de pacotes. Só a última parte de cada grupo tem índice.

## 5. Runtime (console)

### 5.1 Início

`host/hos_main.c`, no lugar onde escolhe `Data/`:

1. Existe `Data.idx` ao lado do `image.bin`? `host/ps5/pak_romfs.c` lê o manifesto e confere: magic, versão (um índice
   da versão 1, de um builder anterior, é recusado com "build the title folder again"), cada seção dentro do arquivo,
   cada grupo tomando seus pacotes em sequência. Abre os 53 pacotes uma vez cada (`O_RDONLY`) e confere de cada um o
   tamanho, o magic, a versão, o número, a parte, o grupo, o `build_id` e onde está o índice do grupo. Lê o índice de
   cada grupo da sua última parte (~23 MB ao todo) e confere cada valor que uma busca vai seguir: cada seção dentro do
   índice, cada nome, filho, pasta e parte dentro dos limites, cada arquivo dentro dos dados da sua parte. (Os SHA-256
   do manifesto e dos índices são conferidos pelo leitor de referência no PC, não no console: o host não tem SHA-256 em
   C, e as checagens acima já impedem que um índice cortado ou trocado leve a uma leitura fora do lugar.)
2. Tudo certo: `hos_romfs_dir = "/pak/romfs"` (uma raiz virtual que não existe no disco).
3. Algo errado: diz no log exatamente o quê ("Data/Tex.1.pak is 3,1 MiB, the manifest says 4096,0 MiB: an incomplete
   copy") e o jogo não acha os arquivos.

Uma busca escolhe o grupo pela primeira parte do caminho e procura só na tabela hash daquele grupo. A listagem da raiz
são as pastas dos grupos, na ordem do manifesto.

### 5.2 Leitura

Um novo `host/ps5/pak_romfs.c` (no lugar de `nup_romfs.c`), e em `host/posix/win32_posix.c` os mesmos desvios que o
`.nup` tinha para caminhos sob a raiz virtual:

| Chamada | Com um caminho sob `/pak/romfs` |
|---|---|
| `CreateFileA` | procura o caminho no índice; o handle guarda {fd do pacote, início, tamanho, posição}; escrita → `ERROR_ACCESS_DENIED` |
| `ReadFile` | `pread(fd do pacote, início + posição, mínimo(pedido, tamanho - posição))` |
| `SetFilePointerEx`, `GetFileSizeEx`, `GetFileType` | só com o tamanho e a posição do handle |
| `GetFileAttributesA` | pasta ou arquivo, só leitura |
| `FindFirstFileA` / `FindNextFileA` / `FindClose` | a lista de filhos da pasta, com o mesmo filtro (`fnmatch`) de hoje |
| `CloseHandle` | libera o handle (o pacote continua aberto) |

Diferenças para o `.nup`: **nenhuma descompressão, nenhum cache, nenhuma alocação por leitura, nenhuma trava** (o
índice é só lido depois do início, e `pread` num fd só de leitura é seguro entre threads). Um caminho com `//` é
normalizado antes da busca (as vozes do jogo pedem `Voice/Resource//Stream`).

### 5.3 Quem lê o romfs sem passar por essas chamadas

| Leitor | Como lê | O que fazer |
|---|---|---|
| `nn::fs` do jogo (`host/nn_fs.c`) | `CreateFileA`/`ReadFile`/`FindFirstFileA` | coberto pela tabela acima |
| tabela de prompts (`host/prompts.c:1385`) | `FindFirstFileA` com padrão | coberto |
| mods (`nn_fs.c` `rom_rel`, `hos_mods_dir_extras`) | comparam a raiz com `hos_romfs_dir` e usam caminhos relativos | continua igual (a raiz é a string virtual) |
| **fontes do menu** (`gpu/vk/vk_game_font.h` `read_file`) | **`fopen` direto** | não passava pelos desvios: com o `.nup` isto falhava em silêncio (o menu caía na fonte embutida). No PS5 o renderer está no mesmo executável que o host, então `read_file` chama `pak_romfs_read` direto para um caminho sob a raiz dos pacotes: sem mudar o `MkwVkHost` nem o `MKWVK_API_VERSION` |

## 6. Builder (PC)

### 6.1 O passo 7 com pacotes (o padrão)

Os pacotes saem **direto do `.nup`**, sem extrair os 26 GB antes (nenhuma pasta temporária; o espaço pedido é ~24,5 GiB
em qualquer drive):

1. Lista o romfs do título mais novo e ordena por caminho (bytes); reparte em grupos por pasta de topo, abrindo uma
   parte nova quando a próxima passaria de 4 GiB (um arquivo maior que 4 GiB iria sozinho numa parte: não há nenhum).
2. Para cada pacote: escreve os dados em `X.pak.part`, copiando cada arquivo do `.nup` (`Nup.copy_to`, o mesmo que a
   extração usa), com o SHA-256 de cada um calculado no caminho, contra o do `.nup` quando ele o tem, e anota os `.zs`
   que não começam como zstd.
3. Com todos os dados escritos: escolhe as substitutas das texturas danificadas (seção 6.2), grava o índice de cada
   grupo no fim da sua última parte, completa o cabeçalho de cada pacote e o renomeia para `X.pak`.
4. Grava `Data.idx.part` → `Data.idx`, por último, e depois `longshot_data.txt`.

**Espaço**: a checagem passa a contar o cluster do drive (pacotes: desprezível; pasta solta: o arredondamento por arquivo,
o que corrige a checagem atual, que só somava o conteúdo).

**Retomar**: a divisão em pacotes e o `build_id` são determinísticos (o carimbo do `.nup`, o limite e a regra), então um
pacote cujos dados já foram escritos inteiros numa tentativa com o mesmo `.nup` (anotado em `longshot_data_packs.json`
na pasta do título, apagado no fim) é mantido; um com os dados cortados é refeito. Os índices dos grupos e o manifesto
são refeitos a cada vez (segundos).

### 6.2 Texturas danificadas

Hoje: copia uma textura inteira do mesmo tipo por cima da danificada (`nup.stand_in_damaged`). Nos pacotes: a mesma
escolha (mesmo sufixo, maior começo de nome igual, tamanho mais próximo, nunca outra danificada), feita sobre o índice,
e a entrada da danificada passa a **apontar para os bytes da substituta** (flag 1). Nenhum byte é copiado, e
`longshot_damaged_files.txt` continua dizendo quais foram trocadas.

### 6.3 Interface e envio

- Uma opção "Dados do jogo como pasta (para mods)" → `--data-folder`; desligada por padrão.
- O envio por FTP manda `Data.idx` e `longshot_data.txt` por último (hoje já manda o `longshot_data.txt` por último).
- 53 arquivos grandes em vez de 186 mil: a cópia fica limitada só pela velocidade da rede ou do drive.

## 7. Testes (sem o jogo)

- **Python** (`tests/test_ps5_data_packs.py`): com um `.nup` sintético (o gerador de `tests/test_ps5_game_data.py`), o
  builder faz os pacotes; um leitor de referência em Python lê cada arquivo pelo índice e compara com o que
  `nup.py --extract` dá. Mais: divisão em partes (com o limite baixado para o teste), textura danificada apontando para a
  substituta, retomar com um `.part` pela metade, pacote de outro build recusado, índice com SHA-256 errado recusado,
  listagem de pasta na ordem certa, caminho com `//`.
- **C** (`tests/test_pak_romfs.py`, como o antigo `nup_romfs_check`): `pak_romfs.c` compilado para o PC lê os mesmos
  pacotes sintéticos e cada arquivo bate com o leitor de Python; com AddressSanitizer. Precisa de um compilador C (aqui
  não há: roda no contêiner do kit ou em outro PC).
- **No console** (com você): início do jogo (log `[ps5] game data: ... packs`), áreas com vozes, a fonte do menu, o Water
  Temple; e o tempo de carregamento de algumas áreas contra a pasta `Data/` solta.

## 8. Riscos

| Risco | Contenção |
|---|---|
| Uma cópia incompleta de um pacote | o início confere o tamanho e o `build_id` de cada pacote e diz qual está errado |
| `Data.idx` de um builder e pacotes de outro | `build_id` no índice e em cada pacote |
| Um leitor do romfs que usa `fopen`/`stat` direto e foi esquecido | levantamento da seção 5.3; no console, um log de "caminho sob /pak/romfs aberto fora dos desvios" não é possível de pegar, então a lista precisa ser completa: um `grep` por `romfs_dir` e `hos_romfs_dir` entra no teste |
| Mods precisam trocar arquivos | `--data-folder`; ou, depois, uma pasta de sobreposição lida antes dos pacotes |
| Programas de FTP com problema em arquivos > 4 GiB | o limite de 4 GiB por pacote |

## 9. Ordem de implementação

1. Formato e builder (Python), com o leitor de referência e os testes da seção 7.
2. `pak_romfs.c` e os desvios em `win32_posix.c`; teste em C no contêiner.
3. As fontes do menu pela função do host (`MKWVK_API_VERSION`).
4. Opção na interface, envio por FTP, README.
5. Novo kit e pacote do builder; teste no console.

## 10. Decisões

1. **Versão 2: o índice de cada grupo dentro do seu último pacote** e um manifesto pequeno no `Data.idx` (a versão 1
   tinha um índice único de 21,8 MB no `Data.idx`). Cada grupo se descreve sozinho, o que abre caminho para trocar ou
   refazer um grupo sem mexer nos outros. Os índices somam ~23 MB na memória do console (um pouco mais que o índice
   único: cada grupo tem a sua tabela hash, de no mínimo 16 KB). Uma pasta de título da versão 1 é recusada pelo
   console e refeita pelo builder.
2. O `longshot_data.txt` continua (`packs nup <tamanho> <data>`): diz de qual `.nup` e em que forma os dados vieram.
3. Os pacotes ficam em `Data/`; com `--data-folder`, `Data/` tem os arquivos soltos e não há `Data.idx`. Trocar de uma
   forma para a outra apaga a anterior (o builder não deixa as duas misturadas).
