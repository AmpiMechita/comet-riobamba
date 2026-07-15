# EIN: Reconocimiento Estrategico Global y Rediseno de Modelo de Negocio

**Clasificacion:** CONFIDENCIAL — Uso interno
**Fecha:** Junio 2026
**Autor:** Director de Estrategia Global, EIN
**Premisa:** El motor es AGNOSTICO AL DOMINIO. Todo son strings con metricas que deben ser cruzadas.

---

## 1. Matriz de Dominios de Aplicacion

| Dominio | Como se aplica el motor | Claims que extrae | Fuente de datos primaria | Tamano de mercado DD tecnica |
|---------|------------------------|-------------------|--------------------------|------------------------------|
| **Defensa y Aeroespacial** | Verifica claims de rendimiento de motores, materiales radar-absorbentes, y propulsores en propuestas de contratistas vs. literatura clasificada/abierta | Empuje (kN/lbf), peso especifico (N/kg), temperatura operativa (°C), factor de carga (g), velocidad Mach, consumo especifico (g/kN·s) | DTIC, NASA NTRS, ArXiv astro-ph, patentes DoD | USD 2-5B anuales en R&D no clasificado |
| **Farmacologia y Biologia** | Cruza claims de eficacia de ensayos clinicos (fase I-III) contra meta-analisis y reportes de seguridad; detecta eficacia inflada o selectividad de datos | IC50 (nM/uM), eficacia (%), p-value, NNT, dosis (mg/kg), half-life (h), biodisponibilidad (%) | PubMed/ClinicalTrials.gov, EMA EPAR, FDA reviews | USD 3-8B anuales en due diligence de pipelines |
| **Mineria y Metalurgia** | Audita claims de procesos de extraccion (lixiviacion, electro-quimica) contra datos operativos reales; detecta promesas de recuperacion sobrevaloradas | Recuperacion (%), ley del mineral (%), consumo de reactivos (kg/t), energia de procesamiento (kWh/t), pureza (%), CAPEX ($/t) | bases regulatorias (ANEEL, SERNAGEOMIN, ANM), papers de mineralurgia | USD 500M-1B en DD de activos mineros |
| **Fisica de Materiales y Metamateriales** | Verifica propiedades de materiales novedosos (superconductores, metamateriales, grafenos) contra mediciones reproducidas; detecta "室温超导" style frauds | Conductividad (S/cm), dureza (GPa), tenacidad (MPa·m^1/2), Tc (K), permeabilidad relativa, banda prohibida (eV) | ArXiv cond-mat, Materials Project, patentes WIPO | USD 1-3B en R&D corporativo de materiales |
| **Quimica y Petroquimica** | Compara rendimientos de catalizadores y procesos quimicos contra datos de planta piloto; detecta escalabilidad ficticia | Conversion (%), selectividad (%), TOF (h-1), rendimiento (g/g cat), presion (bar), temperatura (°C), TON | ArXiv chem, patentes USPTO/EPO, literatura ACS/RSC | USD 1-2B en DD de procesos quimicos |
| **Produccion Industrial y Agronomia de Precision** | Audita claims de rendimiento de sensores IoT, drones agricolas, y sistemas de riego automatizado contra datos de campo | Rendimiento (t/ha), precision (%), area cubierta (ha), latencia (ms), ahorro de agua (%), ROI (%) | Papers de agri-tech, datasets FAO, patentes de maquinaria | USD 500M-1B en agritech DD |
| **Infraestructura y Construccion** | Verifica propiedades de materiales de construccion avanzados (hormigon UHPC, aceros de alta resistencia) contra normas y datos reales | Resistencia (MPa), durabilidad (anos), densidad (kg/m3), absorcion (%), modulo (GPa), coste ($/m3) | Normas ASTM/ISO, papers de ingenieria civil, fichas tecnicas | USD 800M-2B en DD de infraestructura |

**Lectura clave:** Cada dominio usa las mismas 4 operaciones del motor — ingerir, extraer, cruzar, puntuar. Lo unico que cambia es el diccionario de METRIC_PATTERNS y TECH_KEYWORDS.

---

## 2. Mapa de Financiamiento No Reembolsable (Grants) Global

| Dominio | Fuente | Programa Especifico | Monto Tipico | Extranjeros? | URL |
|---------|--------|---------------------|--------------|-------------|-----|
| Defensa/Aeroespacial | **DARPA** (EEUU) | BAA (Broad Agency Announcement) — oficinas MTO, TTO, DSTO | USD 500K - 5M por proyecto / 3-4 anos | Si, pero trabajo debe ejecutarse en EEUU; subcontratista extranjero requiere autorizacion | https://www.darpa.mil/work-with-us/opportunities |
| Defensa/Aeroespacial | **DIU** (Defense Innovation Unit) | Commercial Solutions Opening | USD 1-5M | Si, si hay presencia en EEUU | https://www.diu.mil/work-with-us |
| Farmacologia/Biologia | **NIH** (EEUU) | R01 (Research Project Grant) | USD 250K-500K/directo por ano, tipico 3-5 anos = USD 1-2.5M total | Si, instituciones extranjeras elegibles; menor prioridad que domesticas | https://grants.nih.gov/grants/funding/r01.htm |
| Farmacologia/Biologia | **Wellcome Trust** (UK) | Discovery Awards | GBP 3-5M por proyecto / 5-8 anos | Si, cualquier pais; debe alinearse con misión Wellcome (salud global) | https://wellcome.org/grant-funding |
| Ciencia de Materiales | **Horizon Europe / ERC** (UE) | ERC Consolidator Grant | EUR 2M por 5 anos | PI debe trabajar 50%+ en pais UE/Asociado; equipo puede ser global | https://erc.europa.eu/apply-grant |
| Ciencia de Materiales | **Horizon Europe / EIC** | EIC Accelerator | EUR 0.5-2.5M (grant) + EUR 15M (equity) | Startups de paises UE/Asociados; otros paises como socios | https://eic.ec.europa.eu |
| Manufactura Avanzada | **NIST** (EEUU) | Manufacturing USA Institute / MEP | USD 500K-5M por instituto/ano | Entidades extranjeras como sub-awardees; lead debe ser EEUU | https://www.nist.gov/mep |
| Quimica/Petroquimica | **DOE BES** (Basic Energy Sciences) | Core Research / EFRC | USD 500K-3M/ano | Si, como subcontratista en consorcio con entidad EEUU | https://science.energy.gov/bes/ |
| Mineria/Metalurgia | **Horizon Europe Cluster 5** | Call: Raw Materials / Minerals | EUR 3-8M por consorcio | Si, consorcio debe incluir 3+ paises UE; socios extranjeros elegibles | https://ec.europa.eu/info/funding-tenders |
| Infraestructura | **World Bank / IFC** | IFC InfraTech | USD 500K-5M | Si, pais elegible del Banco Mundial | https://www.ifc.org |

**Dato critico:** En TODAS las fuentes de EEUU (DARPA, NIH, NIST, DOE), la estructura optima para una entidad extranjera es **subcontratista dentro de un consorcio liderado por una entidad estadounidense**. Postular como lead extranjero es posible pero reduce probabilidades al 30-50% segun tipo de programa.

---

## 3. Mapa de Monetizacion B2B (Efectivo Rapido)

| Cliente | Que compra | Cuanto pagan HOY (rango de mercado) | Frecuencia | Esfuerzo de venta | Prioridad EIN |
|---------|-----------|--------------------------------------|------------|-------------------|---------------|
| **Fondos de PE/VC DeepTech** | Due diligence tecnica de un deal: "Esta startup de baterias miente o dice la verdad?" | USD 20K-60K por deal (fuente: r/privateequity, Sphere Partners) | Por deal | Medio (necesitas relaciones con partners de PE) | **ALTA** — Producto existente, margen alto, ciclo de venta 2-4 semanas |
| **Firmas de abogados de patentes** | Invalidity search con IA: "Encuentrame prior art que contradiga los claims de esta patente rival" | USD 3K-15K por busqueda de invalidity (fuente: Cypris, Menteso, PatentScan.ai). Veredictos de jurado en litigio de patentes: USD 4.19B en 2024 | Por caso | Bajo (el abogado ya tiene el presupuesto del cliente) | **ALTA** — El motor extrae claims de patentes por diseno |
| **Corporativos mineros/energeticos** | Auditoria pre-compra: "Este proveedor de tecnologia de lixiviacion cumple lo que promete?" | USD 50K-200K por evaluacion tecnologica (fuente: RSM, OECD DD costs) | Por proyecto | Alto (ciclo de venta 3-6 meses, contacto C-level) | **MEDIA** — Requiere adaptar regex a dominio minero |
| **Agencias regulatorias (gobiernos)** | Licencia anual del sistema + soporte | USD 100K-300K/ano (presupuesto tipico de consultoria para un ministerio) | Anual | Muy alto (procurement publico, 6-12 meses) | **MEDIA-BAJA** — Es el "Star", no el "Cash Cow" |
| **Fondos de cobertura / analistas financieros** | Informes de inteligencia tecnologica ("sector report") para trading | USD 5K-15K por informe suscripcion mensual | Mensual | Medio | **MEDIA** — Requiere volumen para ser rentable |

**La oportunidad inmediata mas clara:** Due diligence tecnica para fondos de Private Equity DeepTech. El motor YA extrae claims de energia. Un fondo que evalua 5 deals/ano a USD 30K cada uno = USD 150K de revenue recurrente con un solo cliente. Dos clientes = USD 300K. No se necesita refactorizar nada. Se vende lo que ya funciona.

---

## 4. Analisis de Brechas: Que le falta al motor para multi-dominio

### 4.1 Regex: Sirve para biologia/quimica?

**No.** El diccionario actual (`METRIC_PATTERNS`) tiene 8 patrones dedicados exclusivamente a energia:

| Patron actual | Tipo | Sirve para otros dominios? |
|---------------|------|---------------------------|
| `(\d+) Wh/kg` | Energia | Solo baterias/energia |
| `(\d+) Wh/L` | Energia | Solo baterias |
| `(\d+)% efficiency` | Generico | Si — con adaptacion |
| `(\d+) mW/cm2` | Energia | Solo fotovoltaica |
| `(\d+) kW/kg` | Energia | Solo motores/baterias |
| `(\d+)$/kWh` | Coste | Si — con adaptacion |
| `(\d+) cycles` | Durabilidad | Parcial (motores, materiales) |
| `(\d+) hours cycling` | Durabilidad | Parcial |

**Patrones que faltan para otros dominios:**

| Dominio | Patrones criticos faltantes |
|---------|----------------------------|
| Farmacologia | `IC50` (nM/uM), `p-value`, `dosis mg/kg`, `half-life (h)`, ` biodisponibilidad (%)`, `NNT` |
| Defensa/Aeroespacial | `empuje kN/lbf`, `Mach`, `consumo especifico g/kNs`, `factor de carga g` |
| Mineria | `recuperacion (%)`, `ley (%)`, `consumo reactivos kg/t`, `CAPEX $/t` |
| Materiales | `dureza GPa`, `tenacidad MPam1/2`, `conductividad S/cm`, `Tc K`, `bandgap eV` |
| Quimica | `conversion (%)`, `selectividad (%)`, `TOF h-1`, `TON`, `rendimiento g/g` |
| Construccion | `resistencia MPa`, `modulo GPa`, `densidad kg/m3`, `absorcion %` |

**Esfuerzo de adaptacion:** Bajo. Cada dominio necesita 5-10 regex adicionales. El patron de diseno es identico al existente. Un ingeniero puede agregar un dominio nuevo en 2-3 horas. El cambio arquitectonico necesario es transformar `METRIC_PATTERNS` de una lista global a un diccionario por dominio: `METRIC_PATTERNS["pharma"] = [...]`.

### 4.2 Base de datos: SQLite soporta grafos de conocimiento?

**No directamente.** SQLite almacena tablas planas. El schema actual tiene una sola tabla `claims` con campos fijos. Esto funciona para el caso de uso actual (claims individuales con metricas) pero no soporta relaciones semánticas entre claims como:

- "El claim A contradice el claim B porque..." (relacion bidireccional con justificacion)
- "El claim C es una generalizacion del claim D" (jerarquia)
- "Los claims E, F, G forman un patron de fraude recurrente en la empresa X" (agregacion)

**Soluciones posibles:**

| Enfoque | Complejidad | Cuando se necesita |
|---------|-------------|-------------------|
| Agregar tabla `claim_relations` (claim_a, claim_b, relation_type, evidence) | Baja | Inmediato — basta para contradicciones 1:1 |
| Migrar a PostgreSQL con extensión pgvector para embeddings | Media | Cuando se necesite busqueda semántica (>10K claims) |
| Neo4j para grafos de conocimiento completos | Alta | Cuando se necesite inferencia multi-hop (no antes de 12 meses) |

**Recomendacion:** Agregar `claim_relations` ahora. Migrar a PostgreSQL solo cuando la base supere 50K claims. Neo4j es over-engineering hasta que el motor demuestre valor comercial en multiples dominios.

### 4.3 LLM: Es lo suficientemente inteligente para bioquimica?

**Depende del modelo.** El sistema actual usa OpenRouter (GPT-oss). Evaluacion honesta:

| Capacidad | GPT-oss (actual) | GPT-4o / Claude 3.5 (superior) | Impacto |
|-----------|------------------|-------------------------------|---------|
| Detectar contradicciones obvias en energia | Si | Si | Ninguno — funciona hoy |
| Detectar contradicciones en bioquimica (ej: "este IC50 contradice el mecanismo de accion") | Riesgoso — puede alucinar | Si, con contexto adecuado | CRITICO — un falso positivo en farmacologia puede tener consecuencias legales |
| Generar informes en lenguaje tecnico por dominio | Generico | Especializado | MEDIO — los clientes de PE esperan lenguaje profesional del dominio |
| Razonar sobre cadenas causales multi-paso | Limitado | Competente | ALTO — contradicciones profundas requieren razonamiento causal |

**El regex es confiable. El LLM es el punto debil para dominios fuera de ingenieria.**

**Estrategia de mitigacion:**
1. En el "Cash Cow" (energia), el LLM solo resume lo que el regex ya extrajo. Riesgo bajo.
2. Para farmacologia/quimica, el LLM debe usarse como **sugeridor de contradicciones**, no como verificador final. El humano confirma.
3. El pipeline DualScoring debe penalizar las contradicciones detectadas solo por LLM (sin respaldo regex) con un factor de confianza < 0.5.

---

## 5. Estrategia "Cash Cow to Star"

### 5.1 El Cash Cow (Vaca Lechera) — Efectivo ESTA SEMANA

**Producto:** Technical Due Diligence Reports para fondos de Private Equity / Venture Capital que invierten en DeepTech energetico.

| Atributo | Detalle |
|----------|---------|
| **Que se vende** | Informe de 10-15 paginas que audita los claims tecnicos de una startup objetivo de inversion. Incluye: claims extraidos, estado de validacion (claimed/disputed/debunked), contradicciones detectadas, y score de rigor cientifico (DualScoring). |
| **Precio** | USD 15K-30K por informe (benchmark de mercado: USD 20K-60K por DD tecnica; EIN es mas barato porque el motor automatiza el 80% del trabajo) |
| **Costo marginal** | ~USD 200 (tiempo de computo + 1 hora de revision humana) |
| **Margen** | >90% |
| **Ciclo de venta** | 2-4 semanas (el socio del fondo ya tiene el deadline de closing) |
| **Cliente target** | Socios de fondos PE/VC con portfolio en energia, baterias, hidrogeno, solar. No marketing — outreach directo por LinkedIn con un informe gratuito de ejemplo (ej: "Auditoria de los claims de QuantumScape"). |
| **Que NO se necesita** | Refactorizar nada. El motor ya funciona. Solo hay que empaquetar la salida como informe profesional (PDF con logo, metodologia, y hallazgos). |

**Proyeccion conservadora:**

| Mes | Clientes | Informes/mes | Revenue/mes | Revenue acumulado |
|-----|----------|-------------|-------------|-------------------|
| 1 | 1 | 1 | USD 20K | USD 20K |
| 2 | 2 | 2 | USD 40K | USD 60K |
| 3 | 3 | 3 | USD 60K | USD 120K |
| 4-6 | 4 | 4-5 | USD 80-100K | USD 360-420K |

**En 6 meses: USD 350K-420K de revenue B2B con el producto actual, sin tocar una linea de codigo del core.**

### 5.2 El Star (Estrella) — Grant/Contrato en 6 meses

**Objetivo:** ERC Consolidator Grant (Horizon Europe) o EIC Accelerator.

| Atributo | ERC Consolidator | EIC Accelerator |
|----------|-----------------|-----------------|
| **Monto** | EUR 2M / 5 anos | EUR 0.5-2.5M (grant) + hasta EUR 15M (equity) |
| **Elegibilidad** | PI debe trabajar 50%+ en UE/Asociado | Startup registrada en UE/Asociado |
| **TRL requerido** | 2-4 (investigacion fundamental) | 6-8 (innovacion lista para mercado) |
| **Narrativa** | "Motor de inteligencia cientifica autonoma para verificacion de claims multidominio" | "Plataforma de DD tecnica automatizada para DeepTech" |
| **Estrategia** | Establecer entidad en pais UE (Estonia e-Residency: 1 semana, EUR 100). Postular como PI con afiliacion europea. | Registrar spin-off en Estonia/Paises Bajos. Usar casos de exito B2B como traccion. |

**Opcion alternativa:** DARPA BAA via consorcio con universidad estadounidense (MIT, Georgia Tech, Stanford). Monto: USD 500K-5M. Requiere Lead Applicant estadounidense.

**Por que 6 meses de espera?** Ningun grant se aprueba sin traccion demostrable. Con 6 meses de revenue B2B (USD 300K+), 10+ informes entregados, y 2-3 clientes recurrentes, la aplicacion cambia de "promesa" a "producto con adopcion". Eso multiplica la probabilidad de aprobacion por 3-5x.

### 5.3 El Engine (Motor) — Refactorizacion para multi-dominio

**Priorizacion de componentes:**

| Componente | Estado actual | Refactorizacion necesaria | Prioridad | Esfuerzo |
|------------|---------------|--------------------------|-----------|---------|
| **METRIC_PATTERNS** | Lista plana, 8 patrones energia | Diccionario por dominio: `PATTERNS["energy"]`, `PATTERNS["pharma"]`, etc. | **P0 — Inmediato** | 2-3 horas por dominio |
| **TECH_KEYWORDS** | 8 categorias energia | Diccionario por dominio con jerarquia | **P0** | 1-2 horas por dominio |
| **ClaimsTracker** | Tabla plana SQLite | Agregar tabla `claim_relations` + campo `domain` en `claims` | **P1 — Mes 1** | 1 dia |
| **SelfMonitor** | (Referenciado en directiva, no implementado en energy_intel_node.py) | Implementar detector de bucles/repetición en generacion de informes | **P1** | 2-3 dias |
| **DualScoring** | (Referenciado en directiva, no implementado en energy_intel_node.py) | Implementar scoring de rigor: penalizar hype, premiar evidencia empirica | **P1** | 2-3 dias |
| **TopicMatrix** | (Referenciado en directiva, no implementado) | Implementar matriz de temas cruzados para detectar patrones transversales | **P2 — Mes 2-3** | 5-7 dias |
| **Scrapers** | ArXiv, USPTO, RSS | Agregar PubMed scraper, DTIC scraper, WIPO scraper | **P2** | 2-3 dias por scraper |
| **LLM Strategy** | Un modelo fijo | Routing inteligente: regex-first, LLM-only como sugeridor con confianza < 0.5 | **P2** | 3-5 dias |

**Secuencia de ejecucion:**

```
SEMANA 1-2:  P0 — Hacer METRIC_PATTERNS y TECH_KEYWORDS parametrizables por dominio
             → Agregar dominio "pharma" (IC50, p-value, dosis) como prueba de concepto
             → Ejecutar contra PubMed con 5 papers de ensayos clinicos
             → Verificar que el motor extrae claims sin errores

SEMANA 3-4:  P1 — Agregar claim_relations a SQLite
             → Implementar SelfMonitor (detector de bucles)
             → Implementar DualScoring (score de rigor)
             → Vender primer informe DD a fondo PE (Cash Cow)

MES 2-3:    P2 — Agregar PubMed scraper + dominio farmacologia completo
             → Agregar dominio mineria (metricas de recuperacion, ley)
             → Vender segundo informe DD + informe a firma de abogados de patentes

MES 4-6:    Preparar aplicacion ERC/EIC con traccion B2B demostrada
             → Establecer entidad en UE (Estonia e-Residency)
             → Iniciar conversaciones con universidad estadounidense para DARPA
```

---

## 6. Modelo de Negocio Consolidado

```
                    ┌──────────────────────────────┐
                    │   CASH COW (Mes 1-6)          │
                    │   DD Tecnica B2B para PE/VC    │
                    │   USD 20-30K/informe           │
                    │   Margen >90%                   │
                    │   Revenue target: USD 350K      │
                    └──────────────┬───────────────┘
                                   │
                                   │ Financia desarrollo
                                   ▼
                    ┌──────────────────────────────┐
                    │   ENGINE (Mes 1-6, paralelo)  │
                    │   Multi-domain refactoring     │
                    │   +3 dominios (pharma, mining,  │
                    │   materials)                   │
                    │   +claim_relations              │
                    │   +DualScoring + SelfMonitor    │
                    └──────────────┬───────────────┘
                                   │
                                   │ Demuestra traccion
                                   ▼
                    ┌──────────────────────────────┐
                    │   STAR (Mes 6-12)              │
                    │   ERC Consolidator: EUR 2M     │
                    │   EIC Accelerator: EUR 2.5M+   │
                    │   DARPA BAA: USD 1-5M           │
                    │   (via consorcio US)             │
                    └──────────────────────────────┘
```

**Metrica norte:** Si en 6 meses no hemos vendido al menos 5 informes DD a fondos PE/VC, el Cash Cow no funciona y hay que pivotar. Si lo hemos vendido, el motor tiene product-market fit y el grant es una aceleracion, no una necesidad.

---

*Documento generado con datos de: DARPA FY2024 Financial Report, NIH Grants Policy, ERC/EIC official portals, Wellcome Trust grant data, OECD due diligence cost studies, market pricing from r/privateequity, Sphere Partners, Cypris, Menteso, PatentScan.ai, RSM US.*
