# PS5 Longshot Plus (`PPSA99198`) — Guía Oficial en Español

**Port Nativo para PlayStation 5 y Builder Multiplataforma (Windows, Linux y macOS) — `v0.3.3-plus`**

> 🌐 **Idioma / Language:** [English (`README.md`)](README.md) · **Español (`README_ES.md`)**

---

## Agradecimientos y Créditos

Antes que nada, nuestro más sincero agradecimiento a:

* **[MagicBeanDev](https://magicbean.dev):** Por crear el motor base de recompilación estática *Longshot*, su renderizador Vulkan y sus continuas optimizaciones de rendimiento y estabilidad.
* **[HeydeMoura](https://github.com):** Por la arquitectura inicial del port nativo a PlayStation 5 (`PS5_Vulkan` / `RADV`) y el desarrollo del *Builder* multiplataforma para Windows y Linux.
* **La comunidad de testers y colaboradores:** Por probar cada compilación en consolas reales (PS5 Fat, Slim y Pro), compartir registros de telemetría (`crash_trace.txt`) y aportar sugerencias clave para pulir el proyecto día a día.

---

## Recomendaciones Críticas de Compilación e Instalación (`v0.3.3-plus`)

### 1. En tu PC (Windows / Linux): Recompilar desde cero es ALTAMENTE RECOMENDADO (obligatorio para aplicar los cambios del núcleo)
* Aunque el Builder permite actualizar compilaciones previas, para **`v0.3.3-plus`** es **altamente recomendado (prácticamente obligatorio) generar la carpeta `PPSA99198` completamente desde cero**.
* **Por qué:** Esta versión actualiza el binario principal (`eboot.bin` / `image.bin`), incorpora el nuevo escáner automático de ROMs por *Title ID* en `/data/longshotplus/roms/`, añade el *watchdog* de telemetría de cómputo (`is_compute`) y aplica las correcciones atómicas de RDNA 2 (`#2088`).
* **Cómo hacerlo:** Antes de pulsar **Build**, elimina o elige una carpeta de salida nueva para que no reutilice archivos intermedios viejos de `longshot-ps5-work`.

### 2. En tu PS5: ¿Es obligatorio borrar la instalación anterior?
* **No es estrictamente obligatorio** borrar toda la carpeta anterior (sobrescribir los archivos funciona), **pero SÍ es altamente recomendado** realizar una instalación limpia eliminando las cachés viejas de shaders (`cache/` y `radv-shader-cache/`) de versiones anteriores.
* **Por qué:** Evita arrastrar *pipelines* compilados con versiones previas o configuraciones residuales que puedan provocar comportamientos inconsistentes.

---

## Cómo Respaldar tus Partidas Guardadas (`user/`) Antes de Actualizar

Todo tu progreso, perfiles, capturas de guardado y ajustes del juego se almacenan dentro de la subcarpeta **`user/`** en tu PS5. **Nunca borres `/data/homebrew/PPSA99198` sin respaldar esta carpeta primero.**

### Paso a paso por FTP (FileZilla / WinSCP / Cyberduck)
1. Conéctate a tu PS5 por FTP (puerto `2121`).
2. Navega hasta:
   `/data/homebrew/PPSA99198/`
3. Descarga a tu PC una copia de seguridad de:
   * **`user/`** *(Carpeta completa: contiene `slot_00/`, `progress.sav`, `caption.sav`, `account.sav` y `option.sav`)*
   * **`longshot_options.ini`** *(Opcional: conserva tus ajustes de gráficos, audio y controles)*
   * **`fsr4/lite/`** *(Opcional: si instalaste los pesos INT8 de AMD FSR 4.1.2)*
4. Ahora ya puedes eliminar la carpeta antigua `/data/homebrew/PPSA99198/` en la PS5 y subir la nueva carpeta **`PPSA99198`** recién compilada.
5. Una vez copiada la nueva versión, vuelve a subir tu respaldo de **`user/`** (y `longshot_options.ini` / `fsr4/lite/` si los guardaste) dentro de `/data/homebrew/PPSA99198/`, sobrescribiendo si te lo solicita.

---

## Carpeta de Datos del Juego (`Data/`) y Estructura de Carpetas en PS5

El builder pasa **todos los archivos del juego** de tu `.nup` a la carpeta del título: **53 paquetes en `Data/` y su
manifiesto `Data.idx`**; cada paquete lleva el índice de su grupo (unos 24,4 GiB en cualquier unidad, sin compresión; los archivos dañados de un volcado incompleto
apuntan a otros completos del mismo tipo). 186.583 archivos sueltos ocuparían 62,5 GiB en una unidad exFAT con clústeres
de 256 KB; los paquetes ocupan los mismos 24,4 GiB en cualquier unidad y se copian por FTP en minutos, no en horas. En la
consola el juego lee todo de los paquetes: **la PS5 no necesita ningún `.nup`** y no abre ninguno. *Game data as a
folder* (`--data-folder`) genera archivos sueltos en su lugar, para mods. Formato:
[docs/ps5-data-packs.md](docs/ps5-data-packs.md).

### Diagrama de cómo quedan ordenadas las carpetas en tu PS5

```text
/data/
└── homebrew/
    └── PPSA99198/                     <-- Carpeta generada por PS5 Longshot Plus Builder
        ├── eboot.bin                  <-- Ejecutable principal recompilado
        ├── image.bin                  <-- Código AArch64 traducido del juego
        ├── Data/                      <-- ★ Los archivos del juego: 53 paquetes (Tex.0.pak, Model.pak, ...), ~24,4 GiB
        ├── Data.idx                   <-- El manifiesto (cada paquete lleva el índice de su grupo): cópialo al final
        ├── longshot_data.txt          <-- De qué .nup vienen los datos
        ├── longshot_env.txt           <-- Parámetros de memoria y rendimiento (PS5 Fat / Pro)
        ├── longshot_options.ini       <-- Configuración del menú interno (se crea al guardar ajustes)
        ├── user/                      <-- ★ TUS PARTIDAS GUARDADAS (¡RESPALDAR SIEMPRE!)
        │   └── slot_00/
        │       ├── progress.sav
        │       └── caption.sav
        ├── fsr4/
        │   └── lite/                  <-- (Opcional) Pesos INT8 de AMD FSR 4.1.2 Lite
        ├── cache/                     <-- Caché de programas de shader (se regenera sola)
        ├── radv-shader-cache/         <-- Caché de pipelines Vulkan RADV (se regenera sola)
        └── logs/
            └── crash_trace.txt        <-- Registro en tiempo real de watchdog y memoria
```

---

## Avisos Importantes de Jugabilidad y Áreas Conocidas

* **⚠️ Coliseo de los Monstruos (*Monster Coliseum*):** **De momento NO se recomienda visitar el Coliseo de los Monstruos.** En esa sala específica existe un *compute shader* (`prog_key=53fcaee4dc45c6ee`) que provoca congelamientos constantes en la GPU RDNA 2 de la PS5 tras ~30 segundos. Ya lo tenemos localizado en los registros y trabajaremos en su corrección para próximas actualizaciones. El mismo *shader* también congeló una cinemática. **Pestaña Debug → GPU freeze shader**: tras una sesión que se congeló, muestra el *shader* en el que se detuvo la GPU (`logs/crash_trace.txt`); **Skip** lo omite desde entonces para poder seguir más allá de ese punto (lo que dibuja ahí falta) y **Skipped shaders** los restaura. Un nuevo congelamiento en él también escribe sus datos en `crash_trace.txt` (líneas `[PS5-PROBE]`) para corregirlo. El builder ahora omite este *shader* por defecto (`ps5/builder/known_gpu_hangs.txt`, escrito en `longshot_env.txt` como `RX_VK_GPU_SKIP`); desactiva *Skip shaders known to hang the GPU* para volver a dibujarlo.
* **Áreas verificadas y estables en PS5 Fat (12 GB):** Bosque Kokiri, Pradera de Hyrule, Rancho Lon Lon, Aldea Kakariko, Dominio de los Zora, Valle Gerudo y Templo del Bosque.
* **Consejo para sesiones largas en PS5 Fat / Slim:** Guarda manualmente antes de cruzar entre muchas zonas abiertas seguidas. Si el sistema detecta que la memoria libre baja del umbral de seguridad (`220 MiB`), cerrará el juego limpiamente (`MEMORY_FLOOR_EXIT`) para proteger tus partidas y evitar el error de sistema `CE-108255-1`; basta con volver a abrir **LONGSHOT PLUS** desde el menú de la PS5 para continuar.

---

## Resumen de Novedades Técnicas en `v0.3.3-plus`

* **Invalidación Exacta de Handles y Retención de Caché de Descriptores (`RX_VK_EXACT_STALE`, `#2343`)**: Registra el ID individual de cada textura eliminada o compactada (`gone_note`) y valida los *handles* en caché mediante `texture_still_resolved` en lugar de invalidar globalmente todos los descriptores del cuadro, reduciendo picos de CPU al cambiar de zona o cerrar menús en PS5.
* **Perfil Interno `Auto (Esta PS5)` Adaptado por Hardware (`PS5 Fat/Slim` vs `PS5 Pro`)**: Configura automáticamente **`1280x720` con `35%` de nitidez** en **PS5 / PS5 Slim** (garantizando sesiones largas sin cierres por memoria al entrar y salir de zonas abiertas) y **`1920x1080 (native)` con `30%` de nitidez** en **PS5 Pro**, junto con `Modo TV`, `AMD FSR 3.1 / FSR 4`, resolución interna `Auto (dinámica)` y `FG integrada 2x`.
* **Perfiles Completos de Entorno en el Builder (`ps5/builder/pipeline.py`)**: Incluye de serie `HOS_PS5_ZERO_FIRST=1`, `RX_VK_IMPORT_CHUNK_MB=4`, `RX_VK_IMPORT_SPAN_MB=16`, `RX_VK_EXACT_STALE=1` y presupuestos ajustados de render y reserva en `longshot_env.txt` tanto para **PS5 / PS5 Slim** (`2560`/`2200 MiB`) como para **PS5 Pro** (`3584`/`1600 MiB`).
* **Corrección de texturas en Zora's Domain congelado (`#2179`)**: Mapea las cargas globales de 128 bits que cruzan el límite de registros reservados (`R206–R207` → registros extendidos `462–463`) en el traductor Ampere-a-Maxwell (`lower_to_maxwell.h`), eliminando los parches magenta y verdes en rocas y nieve con Link Adulto.
* **Nueva Interfaz Oscura PS5 e Icono Retina macOS (`longshot.icns`)**: Rediseño completo de `ps5/builder/app.py` con tema oscuro estilo PlayStation 5, insignia con logo oficial, cuadrícula alineada multiplataforma, validación segura de índices de progreso y generación automática del icono `.icns` desde `icon0.png`.
* **Compilación Oficial en 4 Plataformas**: Paquetes `.app` nativos separados para **macOS Apple Silicon (`arm64`)** y **macOS Intel (`x64`)** junto con **Linux x64 (AppImage)** y **Windows x64 (ZIP portátil)**, cada uno con su archivo `.sha256`.

* **Reloj en Tiempo Real (`Show clock` — `Off` / `12h` / `24h`)**: Nuevo selector en **Gameplay** que muestra la hora local del sistema en la esquina derecha de la barra superior del menú interno y en la esquina superior derecha del HUD (con separación automática respecto al contador de FPS).
* **Soporte de `RX_VK_SKIP_CODE` en Compute Dispatches y Telemetría de `code_key`**: Extensión de `RX_VK_SKIP_CODE` (y registro de `its code:` en `RX_VK_SKIP_PROG`) para *compute dispatches*, permitiendo diagnosticar y aislar shaders de cómputo problemáticos en RDNA 2 (como `prog_key=53fcaee4dc45c6ee` en el Coliseo de los Monstruos).
* **Perfil Mejorado para PS5 Pro (`13.2 GiB` de memoria directa)**: Presupuesto de renderizador ampliado a 3.5 GiB (`HOS_PS5_RENDER_MB=3584`), reserva de texturas ajustada (`HOS_PS5_TEX_RESERVE_MB=1600`) y mayor retención de texturas a 1024 texels (`RX_VK_EVICT_MIN_UNUSED=60`) sin afectar la estabilidad de PS5 Fat / Slim.
* **Plegado de Comparaciones con Signo en CPU (`A64_SUB_V`, `#1871`)**: Simplifica ~170,000 comparaciones con signo del código recompilado a una sola instrucción de CPU x86-64, reduciendo la carga del procesador y el tamaño de `image.bin` en PS5.

### Comparativa de Perfiles: PS5 Fat / Slim vs PS5 Pro (`v0.3.3-plus`)

| Característica / Parámetro | PS5 Fat / Slim (`base`) | PS5 Pro (`pro`) |
| :--- | :--- | :--- |
| **Perfil del kernel (`attribute3`)** | `0x140040` (Modo base) | `0x8540040` (High CPU Frequency) |
| **Memoria directa disponible** | `12,016 MiB` (~11.7 GiB) | `13,232 MiB` (~12.9 GiB) |
| **Resolución máxima de texturas (`RX_VK_TEX_MAX_DIM`)** | `512` texels | `1024` texels (Nativa completa) |
| **Umbral de omisión de mipmaps (`RX_VK_TEX_SKIP_MB`)** | `2 MiB` | `64 MiB` (Por defecto sin recorte agresivo) |
| **Presupuesto de renderizador (`HOS_PS5_RENDER_MB`)** | `2,560 MiB` (2.5 GiB) | `3,584 MiB` (3.5 GiB) |
| **Reserva libre para el juego (`HOS_PS5_TEX_RESERVE_MB`)** | `2,200 MiB` | `1,600 MiB` |
| **Retención de texturas/targets (`RX_VK_EVICT_MIN_UNUSED`)** | `30` presents | `60` presents |
| **Rendimiento estimado (Bosque Kokiri 1080p + FG 2x)** | ~45 FPS mostrados | ~63–68 FPS mostrados |
| **Salida y nitidez por defecto (`Auto (Esta PS5)`)** | `1280x720` (`35%` nitidez — sesiones largas sin cierres) | `1920x1080 (native)` (`30%` nitidez; soporta hasta 4K) |
| **Upscaler y Frame Generation por defecto** | AMD FSR 3.1 (o FSR 4.1.2 Lite) + Built-in FG 2x | AMD FSR 3.1 (o FSR 4.1.2 Lite) + Built-in FG 2x |
* **Corrección de cuelgues atómicos de cómputo RDNA 2 / RADV (`#2088`):** Serializa los bucles atómicos de punto flotante por subgrupo mediante `OpGroupNonUniformElect` (`SubgroupCasLoop`), eliminando cuelgues de GPU de 2 segundos en pases de iluminación de templos.
* **Escáner dedicado de ROMs (`/data/longshotplus/roms/`) y validación de Title ID (`ps5_is_oot_nup`):** Detecta automáticamente cualquier `.nup` válido (`0400486024DEC000`) en `/data/longshotplus/roms/` o rutas alternativas.
* **Salida directa FSR 3.1 (`#2085`) y salto hacia atrás a alto FPS (`#2071`):** Ahorra ~1 ms por fotograma en FSR 3.1 y corrige la altura del *backflip* por encima de 60 FPS (`HOS_FPS_TAKEOFF`).
* **Gestión de memoria en 4 niveles para PS5 Fat:** `zone_boost` proactivo (`< 2420 MiB`), bloqueo de re-expansión ASTC, purga de *render targets* obsoletos (`1152 / 512 MiB`) y piso preventivo `MEMORY_FLOOR_EXIT` (`220 MiB`) con `RX_VK_TEX_MAX_DIM=512` y `RX_VK_TEX_SKIP_MB=2` (~1.88 GiB libres verificados).
* **Telemetría ampliada en `crash_trace.txt`:** Registra `is_compute=1|0`, `prog_key`, `free_mem` y `zone_boost` en tiempo real sin búfer (`O_SYNC`).
* **Mejoras del Builder (`#59`, `#62`, `#63`):** Incluye `PS5LongshotPlusBuilder-cli.cmd` redirigible en Windows, modo de bajo consumo de memoria (`2–3 GB` de RAM) y corrección del paso 6 en PyQt6.

### Novedades en v0.3.3-plus
- **Puesta a cero previa al mapeo de memoria guest (`#68`, `HOS_PS5_ZERO_FIRST=1`):** limpia los bloques de memoria directa antes de mapearlos al espacio del juego para evitar cierres por puntero nulo al cargar partidas.
- **Chunks de importación GPU de 4 MB por defecto (`#74`, `RX_VK_IMPORT_CHUNK_MB=4`, `RX_VK_IMPORT_SPAN_MB=16`):** reduce páginas sin usar en PS5, liberando 200–330 MiB reales en PS5 Fat / Slim.
- **Búsqueda O(1) de mutex por índice embebido (`#75`, `HOS_MUTEX_IX=1`):** guarda el índice del objeto host en `nn::os::MutexType + 8`, reduciendo la carga de CPU en sincronización.
- **Mejoras de memoria y estabilidad upstream (`#2194`, `#2258`) + Watchdog Dual + `PS5_PayloadSDK` actualizado (`55a2de04`).**

### Notas Estructurales y de Plataforma (v0.3.3-plus)
- **Builders Nativos para macOS e Interfaz Oscura PS5:** Añade paquetes `.app` autónomos para `macos-arm64` (Apple Silicon) y `macos-x64` (Intel) con Python 3.13, PyQt6, LLVM/Clang 23, herramientas Mach-O, icono Retina `longshot.icns`, rediseño oscuro estilo PS5 y corrección gráfica de Zora's Domain (`#2179`).
- **Memoria y Sincronización PS5 (`#68`, `#74`, `#75`, `#2194`, `#2258`):** Puesta a cero previa al mapeo (`HOS_PS5_ZERO_FIRST=1`), *chunks* de importación GPU de 4 MB (`+200–330 MiB` libres en PS5 Fat/Slim), búsqueda O(1) de *mutex* por índice (`HOS_MUTEX_IX=1`), decodificación ASTC rápida vía LDS, Watchdog Dual (`crash_trace.txt`) y `PS5_PayloadSDK` (`55a2de04`).
- **Regeneración Inicial de Shaders:** Al actualizar a `v0.3.3-plus`, el Builder invalida una sola vez `longshot-ps5-work` debido al nuevo sello del SDK y memoria Vulkan, regenerando los ~38,809 *shaders* conocidos; las siguientes compilaciones vuelven a tardar segundos.


---

## Descarga y Ejecución Multiplataforma (Windows, Linux y macOS)

Descarga el paquete correspondiente a tu arquitectura desde [**Releases (`groovy2312/PS5_Longshot_Plus`)**](https://github.com) (cada archivo incluye su suma de verificación `.sha256`):

| Sistema Operativo | Paquete Oficial | Instrucciones de Inicio |
|---|---|---|
| **Windows (x64)** | `PS5LongshotPlusBuilder-<version>-windows-x64.zip` | Descomprime toda la carpeta y ejecuta `PS5LongshotPlusBuilder.exe` (mantén todos los archivos juntos). |
| **Linux (x64)** | `PS5LongshotPlusBuilder-<version>-x86_64.AppImage` | Otorga permisos con `chmod +x PS5LongshotPlusBuilder-*.AppImage` y ejecútalo. |
| **macOS (Apple Silicon)** | `PS5LongshotPlusBuilder-<version>-macos-arm64.zip` | Descomprime `PS5LongshotPlusBuilder.app`. Si Gatekeeper muestra aviso, ejecuta `xattr -cr PS5LongshotPlusBuilder.app` y ábrela. |
| **macOS (Intel)** | `PS5LongshotPlusBuilder-<version>-macos-x64.zip` | Descomprime `PS5LongshotPlusBuilder.app`. Si Gatekeeper muestra aviso, ejecuta `xattr -cr PS5LongshotPlusBuilder.app` y ábrela. |

---

## Instalación y Uso en PlayStation 5

1. **Prepara tu copia legal del juego:** Programa `0400486024DEC000`, actualización **`v131072`** (`build e0f3ccfa`) en formato `.nup`.
2. **Compila la carpeta `PPSA99198` en tu PC/Mac:**
   * Abre **PS5 Longshot Plus Builder**, selecciona tu archivo `.nup`, la carpeta de salida y tu modelo de consola (**PS5 / PS5 Slim** o **PS5 Pro**).
   * Pulsa **Build**. Al finalizar obtendrás la carpeta **`PPSA99198`** (**nunca la compartas**, contiene código derivado de tu juego).
3. **Copia los archivos a la PS5 por FTP (puerto `2121`):**
   * Sube la carpeta completa **`PPSA99198`** a `/data/homebrew/PPSA99198/` (o usa el botón **Send to PS5** del Builder).
   * La carpeta ya incluye los datos del juego en **`Data/`** (53 paquetes, unos 24,4 GiB) y **`Data.idx`**: es la copia larga. No hace falta copiar ningún `.nup` a la consola. Si usas otro programa FTP, copia `Data.idx` al final.
4. **Inicia el juego:** Abre **LONGSHOT PLUS** desde la pantalla principal de la PS5 o tu lanzador homebrew. La primera visita a cada zona compila sus *shaders* y los guarda en caché; las siguientes visitas serán fluidas.

---

## Menú Interno del Juego y Controles DualSense

* **Abrir y cerrar el menú interno:** Pulsa **Clic en el Panel Táctil (Touchpad) + Options** al mismo tiempo.
* **Navegar por el menú:** `L1` / `R1` cambian de pestaña, la cruceta selecciona filas, **Círculo** confirma/cambia opciones y **Equis** retrocede o cierra el menú.

### Opciones principales en PS5 (`Gráficos`)
* **Perfil de calidad (`Auto (Esta PS5)`):** Detecta automáticamente si estás ejecutando el perfil **PS5 Fat / Slim** (`1280x720`, `35%` nitidez para sesiones largas sin cierres) o **PS5 Pro** (`1920x1080 (native)`, `30%` nitidez).
* **Resolución de salida:** `1280x720`, `1920x1080`, `2560x1440` o `3840x2160` (los cambios aplican tras reiniciar el título).
* **Upscaler:** `AMD FSR 3.1` por defecto en todas las PS5, o `AMD FSR 4` automático si copias los pesos `lite/`.
* **Generación de cuadros:** `2x (game at 30 fps)` activada de serie mediante **FG integrada** (`PS5_MihawkGen`).

### Controles DualSense por defecto

| Nintendo Switch | DualSense (PS5) |
|---|---|
| **A / B** | **Círculo / Equis** |
| **X / Y** | **Triángulo / Cuadrado** |
| **L / R** | **L1 / R1** |
| **ZL / ZR** | **L2 / R2** |
| **− / +** | **Clic en Touchpad / Options** |

---

## Opcional: Activar AMD FSR 4.1.2 (Lite) en PS5

Por defecto, **PS5 Longshot Plus** utiliza **AMD FSR 3.1**. Si deseas activar **AMD FSR 4.1.2 (Lite INT8)** en tu PS5:
1. Descarga **`beamng-fsr4-linux-0.3.0.tar.gz`** desde [Mob1K7105/beamng-fsr4-linux Releases](https://github.com).
2. Descomprime el archivo y extrae la carpeta **`lite/`** que contiene los pesos INT8.
3. Súbela por FTP a tu PS5 en la ruta: `/data/homebrew/PPSA99198/fsr4/lite/`.
4. Al iniciar el juego, **PS5 Longshot Plus** detectará los pesos automáticamente y cambiará el escalador a **AMD FSR 4**.

---

## Uso de Mods (`RomFS`)

Coloca tus mods en `/data/homebrew/PPSA99198/mods/<nombre_del_mod>/romfs/...`.
* Las carpetas que empiecen por `-` o `_` quedan desactivadas.
* Si dos mods modifican el mismo archivo, prevalece el que se ordene al final alfabéticamente (usa prefijos como `01-...`, `02-...` para controlar el orden).
* Solo se cargan mods de **RomFS** (los parches de `exefs` como `.pchtxt` o `.ips` no aplican porque el código del juego se recompila estáticamente en PC).

---

## Solución de Problemas Frecuentes

* **El juego no aparece en la pantalla principal de la PS5:** Verifica que `eboot.bin` esté directamente dentro de `/data/homebrew/PPSA99198/eboot.bin` y que tu entorno homebrew (`etaHEN` / `ShadowMountPlus`) escanee `/data/homebrew/`.
* **Se queda en pantalla negra antes de los logos:** Comprueba que la carpeta `/data/homebrew/PPSA99198/Data/` y `Data.idx` se hayan copiado completos (el log del juego nombra un paquete incompleto) y que tu `.nup` corresponda exactamente al programa `0400486024DEC000` actualización `v131072`.
* **El Builder se detiene por falta de memoria en PC:** Baja el selector **Memory to use** a `2 GB` o `3 GB` y vuelve a pulsar **Build**; retomará la compilación desde donde se quedó.

---

## Licencia

**PS5 Longshot Plus** es software libre bajo licencia **GNU General Public License v3.0 o posterior (`GPL-3.0-or-later`)**. *The Legend of Zelda* y *Ocarina of Time* son marcas registradas de Nintendo; este proyecto no incluye archivos ni claves del juego.
