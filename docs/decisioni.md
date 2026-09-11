# Registro delle decisioni tecniche

Ogni voce risponde a quattro domande: cosa si e' scelto, cosa si e' scartato,
perche', e con quale misura la scelta si potrebbe confermare o smentire.

Le voci sono numerate in ordine cronologico e non vengono rinumerate: se una
decisione viene rivista, si aggiunge una voce nuova che cita quella superata.

---

## Fase 0 — Scaffolding e raccolta dati

### 1. La raccolta dati precede tutto il resto

**Decisione.** La Fase 0 e' l'unica cosa realizzata prima di qualsiasi altra
parte del progetto, KB e pianificatore compresi.

**Alternative considerate.** Costruire prima la base di conoscenza e il grafo
tempo-espanso, che sono le parti "nobili" per un corso di Ingegneria della
Conoscenza, e occuparsi dei dati in un secondo momento.

**Motivo.** Un feed GTFS Real-Time e' una fotografia dell'istante presente:
nessuna agenzia pubblica lo storico dei ritardi. Il dataset su cui si reggono la
Fase 3 e la Fase 5 non esiste finche' non lo costruiamo giorno per giorno, e ogni
giorno in cui il collector non gira e' un giorno perso in modo definitivo. La KB
e il grafo, al contrario, si possono scrivere in qualunque momento perche' il
GTFS statico e' scaricabile quando si vuole.

**Come si potrebbe verificare.** Contare, a fine progetto, i giorni di raccolta
effettivamente usati nella griglia sperimentale della Fase 5. Se fossero meno di
quelli disponibili sul calendario del progetto, la differenza misurerebbe
esattamente il costo di aver ritardato l'avvio.

---

### 2. Python 3.14.6 invece di ripiegare su una versione piu' conservativa

**Decisione.** Si usa l'interprete gia' presente sulla macchina, Python 3.14.6.

**Alternative considerate.** Installare Python 3.12, che al momento e' la
versione con il supporto piu' ampio nell'ecosistema scientifico.

**Motivo.** Il rischio concreto era l'assenza di wheel precompilate per `cp314`
su Windows, in particolare per `clingo` (che altrimenti richiederebbe CMake e
MSVC) e per `pyarrow`. Il rischio e' stato verificato invece che ipotizzato, con
`pip install --only-binary=:all: --dry-run`: esistono wheel `cp314` per tutte e
dodici le dipendenze. Verificato anche a livello funzionale, non solo di
installazione: `clingo.Control` risolve un programma di prova, il roundtrip
protobuf di un `FeedMessage` conserva i ritardi, e `zoneinfo` risolve
`Europe/Rome`.

**Come si potrebbe verificare.** Rieseguire `pip install --only-binary=:all: -r
requirements.txt` in un venv pulito. Se una qualsiasi wheel sparisse dall'indice,
il comando fallirebbe subito invece di avviare una compilazione.

---

### 3. Versioni delle dipendenze fissate in modo esatto

**Decisione.** `requirements.txt` usa `==` su tutte le dipendenze dirette, e
l'installazione avviene sempre con `--only-binary=:all:`.

**Alternative considerate.** Intervalli di versione (`>=`), che invecchiano
meglio e riducono i conflitti.

**Motivo.** Il deliverable valutato di questo progetto e' una campagna
sperimentale. Un intervallo di versioni renderebbe i numeri riportati nella
documentazione non riproducibili da chi legge: una risoluzione diversa delle
dipendenze puo' cambiare il comportamento di `scikit-learn` o di `pandas` fra una
minor e l'altra. Il flag `--only-binary` trasforma l'assenza di una wheel in un
errore immediato invece che in una compilazione da sorgente di venti minuti
destinata a fallire.

**Come si potrebbe verificare.** Installare il progetto in due venv puliti a
distanza di mesi e confrontare `pip freeze`: devono coincidere sulle dipendenze
dirette.

---

### 4. `tzdata` dichiarata esplicitamente pur essendo una dipendenza indiretta

**Decisione.** `tzdata` compare in `requirements.txt` anche se `pandas` la
installerebbe comunque su Windows.

**Alternative considerate.** Lasciarla implicita; oppure evitare `zoneinfo` e
lavorare con l'ora locale della macchina.

**Motivo.** Windows non include il database IANA dei fusi orari, quindi la
`zoneinfo` della libreria standard non funzionerebbe senza. Il nostro codice ne
dipende **direttamente**: la `service_date` del GTFS e' un concetto in ora locale
e va calcolata correttamente anche nei giorni di cambio dell'ora legale. Una
dipendenza diretta lasciata implicita si rompe silenziosamente il giorno in cui
la dipendenza intermedia smette di richiederla.

**Come si potrebbe verificare.** Disinstallare `tzdata` in un venv di prova: il
collector deve continuare a raccogliere, emettendo un avviso e ripiegando sul
fuso di sistema (comportamento previsto e collaudato), non interrompersi.

---

### 5. `urllib.request` invece di `requests`

**Decisione.** Tutto l'HTTP passa dalla libreria standard.

**Alternative considerate.** `requests`, che offre timeout separati per
connessione e lettura, gestione trasparente delle sessioni e un'API piu' comoda.

**Motivo.** `requests` non fa parte dello stack autorizzato per il progetto, e
introdurlo per una manciata di chiamate GET non lo giustifica. La conseguenza
tecnica va dichiarata: `urllib` espone un solo parametro `timeout`, che copre le
operazioni sul socket senza distinguere fra connessione e lettura. Nel nostro
caso e' accettabile perche' il timeout complessivo (20 s) e' comunque molto
inferiore all'intervallo di polling (60 s), quindi una risposta lenta non puo'
far slittare il tick successivo.

**Come si potrebbe verificare.** Misurare, sul manifest di una giornata reale, la
distribuzione del tempo di risposta del feed. Se la coda superasse i 20 s con
frequenza non trascurabile, il timeout unico diventerebbe un problema e la
decisione andrebbe rivista.

---

### 6. Si raccolgono `trip_updates` e `vehicle_positions`

**Decisione.** Per ogni citta' si interrogano entrambi i feed; solo
`trip_updates` e' obbligatorio.

**Alternative considerate.** Solo `trip_updates`, che e' l'unica fonte
effettivamente necessaria; oppure anche `service_alerts`.

**Motivo.** `trip_updates` e' indispensabile perche' contiene i ritardi.
`vehicle_positions` costa poco spazio e serve da ridondanza: se dopo due
settimane i `trip_updates` di un'agenzia si rivelassero poveri o intermittenti,
dalle posizioni si potrebbero ricostruire i passaggi, mentre a posteriori non si
puo' recuperare nulla. `service_alerts` e' stato escluso perche' spiegherebbe
solo gli outlier e rischia di restare inutilizzato, allargando la Fase 3.

**Come si potrebbe verificare.** A fine raccolta, contare quante osservazioni di
ritardo si ottengono dai soli `trip_updates` e quante se ne otterrebbero
integrando le posizioni. Se il secondo numero non fosse significativamente
maggiore, la ridondanza sarebbe stata spazio sprecato.

---

### 7. Dump salvati non compressi, in `.pb`

**Decisione.** I dump vengono scritti cosi' come arrivano, senza `gzip`.

**Alternative considerate.** `.pb.gz`, che ridurrebbe l'occupazione di circa due
terzi.

**Motivo.** Lo spazio disponibile (565 GB liberi) non e' il vincolo stringente, e
la deduplica per `header.timestamp` riduce gia' il volume alla sola informazione
nuova. File non compressi si leggono piu' velocemente nella Fase 3, che deve
attraversare decine di migliaia di dump, e restano ispezionabili singolarmente
senza passaggi intermedi.

**Come si potrebbe verificare.** Misurare il volume reale dopo il primo giorno di
raccolta e proiettarlo sulla durata prevista della campagna. Se superasse una
decina di GB per citta', la compressione tornerebbe conveniente. **Questo numero
va misurato e annotato qui appena la raccolta parte.**

---

### 8. Raggruppamento dei dump per data locale della citta'

**Decisione.** La cartella giornaliera usa la data nel fuso orario dell'azienda
di trasporto, non la data UTC; il manifest conserva entrambi gli istanti.

**Alternative considerate.** Raggruppare per data UTC, che e' immune ai fusi e ai
cambi d'ora.

**Motivo.** La `service_date` del GTFS e' definita in ora locale. Raggruppando per
data locale, la cartella di un giorno contiene esattamente le osservazioni di
quel giorno di servizio e il join della Fase 3 non deve ricostruire nulla. Con la
data UTC, ogni giornata italiana sarebbe spezzata su due cartelle.

**Come si potrebbe verificare.** Contare, in Fase 3, quante osservazioni cadono
fuori dalla `service_date` a cui la cartella le assegna. Con il raggruppamento
locale devono essere solo quelle delle corse a cavallo della mezzanotte, che il
GTFS rappresenta con orari oltre le 24:00.

---

### 9. Sottocartella per tipo di feed

**Decisione.** Il percorso e'
`data/raw/rt/<citta>/<data>/<tipo_feed>/<HHMMSS>.pb`, con il tipo come cartella e
non come suffisso del nome file.

**Alternative considerate.** `<HHMMSS>_trip_updates.pb` nella cartella del
giorno, piu' aderente alla struttura indicata nella specifica iniziale.

**Motivo.** La Fase 3 legge solo i `trip_updates`. Una cartella dedicata rende la
selezione una questione di percorso invece che di filtro sul nome del file, il
che elimina un'intera classe di errori silenziosi, e tiene ogni cartella attorno
al migliaio di file invece che al doppio.

**Come si potrebbe verificare.** Se in Fase 3 comparisse anche una sola
osservazione proveniente da un `vehicle_positions` letto per sbaglio, la
separazione per cartella non starebbe funzionando.

---

### 10. Deduplica dei dump tramite `header.timestamp`

**Decisione.** Se il `header.timestamp` del feed appena scaricato coincide con
quello dell'ultimo salvato, il dump non viene scritto; il manifest registra
comunque l'interrogazione con esito `duplicato`. Se il feed non valorizza quel
campo, si conserva tutto.

**Alternative considerate.** Salvare sempre; oppure confrontare l'impronta
SHA-256 dell'intero payload.

**Motivo.** Le agenzie rigenerano il feed con una cadenza propria (tipicamente
30-120 s) non sincronizzata con la nostra, quindi interrogando ogni 60 s capita
spesso di riottenere la stessa fotografia. Il punto non e' risparmiare disco: se
conservassimo i duplicati, la Fase 3 conterebbe piu' volte la stessa osservazione
e **gonfierebbe artificialmente la numerosita' campionaria** su cui si calcolano
medie e deviazioni standard, che e' precisamente il vizio metodologico che i
vincoli di valutazione vietano. L'impronta dell'intero payload e' stata scartata
perche' alcuni feed includono campi che cambiano a ogni generazione pur senza
portare informazione nuova. Nel caso di `header.timestamp` assente si preferisce
il duplicato all'osservazione persa, perche' il secondo errore e' irreversibile.

**Come si potrebbe verificare.** Confrontare, su una giornata, il numero di
passaggi distinti `(trip_id, stop_id, service_date)` estratti dai dump salvati con
quello che si otterrebbe salvando tutto: devono coincidere. Se il secondo fosse
maggiore, la deduplica starebbe scartando informazione vera.

**Aggiornamento del 2026-08-25: il risparmio di spazio non si e' verificato.**
Sui primi 13 giri di raccolta reale, cioe' 52 interrogazioni fra Roma e Torino su
entrambi i feed, gli esiti sono stati **52 `salvato` e 0 `duplicato`**: nessuna
delle due agenzie ha mai ripresentato lo stesso `header.timestamp` a un minuto di
distanza. Entrambe rigenerano il feed piu' spesso di quanto lo interroghiamo,
quindi su queste due citta' la deduplica **non elimina nulla** e la proiezione di
1,34 GB al giorno della voce 28 va presa per intera, senza sconti.

Il campione e' pero' piccolo e tutto diurno (16 minuti attorno alle 13:30 di un
martedi'). Nelle ore notturne, con poche corse in servizio, e' plausibile che il
feed resti fermo piu' a lungo e qualche duplicato compaia: la misura va rifatta
su una giornata intera prima di considerarla definitiva.

La decisione **resta corretta**, ma per una ragione sola invece che due. Il
risparmio di spazio era un beneficio atteso e non si e' materializzato; la tutela
metodologica contro il doppio conteggio in Fase 3 resta intera, ed e' quella che
giustifica la scelta: se un giorno una delle due agenzie rallentasse la propria
cadenza di rigenerazione, senza deduplica ci ritroveremmo a contare piu' volte la
stessa osservazione mentre calcoliamo medie e deviazioni standard, e non ce ne
accorgeremmo. Una tutela che costa nulla e non serve quasi mai e' comunque una
tutela.

Va registrato come **risultato negativo misurato**, ed e' materia per la sezione
del documento sulle scelte di progetto: il beneficio che avevamo attribuito alla
deduplica era una previsione non verificata, e la verifica l'ha smentita.

---

### 11. Validazione semantica del payload, oltre al parsing protobuf

**Decisione.** Un payload e' accettato solo se non inizia come un documento di
markup, se `ParseFromString` riesce, **e** se `header.gtfs_realtime_version` e'
valorizzato.

**Alternative considerate.** Fidarsi del solo `ParseFromString`.

**Motivo.** Il terzo controllo sembra ridondante, dato che
`gtfs_realtime_version` e' un campo *required* di proto2, ma non lo e': **e' stato
verificato sperimentalmente che protobuf applica il vincolo dei campi obbligatori
solo in scrittura**. In lettura accetta senza protestare un messaggio che ne e'
privo, restituendo una stringa vuota. Il test
`test_un_protobuf_senza_versione_non_e_un_feed_gtfs_rt` costruisce quei byte a
mano proprio perche' l'API Python si rifiuterebbe di serializzarli, mentre un
server malconfigurato puo' restituirli. Senza questi controlli il rischio
concreto e' accumulare settimane di file `.pb` che in Fase 3 si rivelano pagine
HTML di errore, quando non c'e' piu' modo di rimediare.

**Come si potrebbe verificare.** Contare le righe con esito `payload_non_valido`
nei manifest. Se fossero piu' di una frazione trascurabile, il feed andrebbe
ispezionato guardando i file conservati in `_scarti/`.

---

### 12. I payload rifiutati vengono conservati

**Decisione.** Un payload che non supera la validazione finisce in
`_scarti/<tipo_feed>/<HHMMSS>.bin`, non viene buttato.

**Alternative considerate.** Scartarlo registrando solo l'evento nel log.

**Motivo.** Se un giorno il feed cambia formato o l'agenzia introduce
un'autenticazione, vogliamo poter capire **cosa** e' arrivato, non solo sapere che
era illeggibile. Il costo e' trascurabile perche' questi casi devono essere rari
per costruzione.

**Come si potrebbe verificare.** Alla prima anomalia, aprire un file di
`_scarti/` deve bastare a diagnosticare la causa senza dover riprodurre il
problema.

---

### 13. Manifest giornaliero con una riga per ogni interrogazione

**Decisione.** Ogni interrogazione, riuscita o fallita, scrive una riga in
`_manifest.csv` con istante UTC e locale, tipo di feed, esito, stato HTTP,
tentativi, byte, `header.timestamp`, numero di entita' e file prodotto.

**Alternative considerate.** Registrare solo i salvataggi; oppure affidarsi al
solo file di log.

**Motivo.** Senza le righe di fallimento manca il **denominatore**: la copertura
della raccolta (quota di interrogazioni andate a buon fine) non sarebbe
calcolabile a posteriori. La copertura e' un indicatore di qualita' del dataset
che va riportato nella documentazione, perche' qualifica tutti i risultati
sperimentali che ne dipendono. Un CSV e' preferibile al log perche' e'
direttamente leggibile in `pandas` senza doverlo interpretare.

**Come si potrebbe verificare.** Per ogni giornata, il numero di righe del
manifest deve essere pari a (giri effettuati x feed configurati). Uno scarto
segnalerebbe interrogazioni non registrate, quindi una copertura sovrastimata.

---

### 14. Snapshot giornaliero dell'orario statico, archiviato solo se cambia

**Decisione.** Il collector scarica il GTFS statico una volta al giorno per
citta', ne calcola lo SHA-256 e conserva l'archivio solo quando l'impronta e'
diversa dall'ultima. Lo stato del controllo sta in un file JSON su disco.

**Alternative considerate.** Scaricare il GTFS statico una volta sola all'inizio
del progetto; oppure a fine campagna; oppure ogni giorno conservando tutto.

**Motivo.** E' la decisione con l'impatto piu' alto di tutta la Fase 0. Gli
identificativi di corsa del feed real-time hanno senso **solo** rispetto alla
versione dell'orario statico in vigore quel giorno, e le agenzie ripubblicano
l'orario ogni poche settimane cambiando i `trip_id`. Con un solo scaricamento a
fine campagna, una parte dei dump gia' raccolti diventerebbe impossibile da
interpretare e i giorni corrispondenti andrebbero buttati. Conservare solo le
revisioni distinte tiene il costo a pochi MB per revisione invece che per giorno.
Lo stato su file, e non in memoria, evita di riscaricare decine di MB a ogni
riavvio del processo.

**Come si potrebbe verificare.** In Fase 3, misurare la quota di
`(trip_id, service_date)` del real-time che trova corrispondenza nell'orario
statico archiviato per quel giorno. Deve restare vicina al 100% anche a cavallo
di una revisione dell'orario; con un unico snapshot crollerebbe.

---

### 15. Cadenza a tick fissi invece di attesa dopo il lavoro

**Decisione.** L'istante del giro successivo si calcola come
`prossimo_tick += intervallo`, non come "dormi 60 secondi dopo aver finito". Se un
giro sfora, i tick arretrati vengono saltati per riallinearsi.

**Alternative considerate.** `time.sleep(60)` al termine di ogni giro.

**Motivo.** La seconda forma somma la durata di ogni scaricamento all'attesa,
facendo scivolare l'istante di campionamento di parecchi minuti nell'arco di una
giornata. Il campionamento smetterebbe di essere regolare proprio mentre lo
dichiariamo tale, e la cadenza effettiva diventerebbe dipendente dalla latenza
del server dell'agenzia.

**Come si potrebbe verificare.** Calcolare, sul manifest di una giornata, media e
deviazione standard dell'intervallo fra interrogazioni consecutive: la media deve
restare a 60 s senza deriva fra la prima e l'ultima ora.

---

### 16. Nessun ritentativo sugli errori HTTP 4xx

**Decisione.** I 4xx interrompono subito la sequenza di tentativi; i 5xx e gli
errori di rete vengono ritentati con backoff esponenziale e jitter.

**Alternative considerate.** Ritentare in modo uniforme su qualunque errore.

**Motivo.** Un 401 o un 404 non si risolvono riprovando fra due secondi:
insistere significherebbe solo martellare il server dell'agenzia con richieste
che sappiamo destinate a fallire, e ai loro occhi saremmo indistinguibili da un
client difettoso. Il jitter sul backoff evita che, dopo un guasto comune (per
esempio la rete di casa che cade), tutte le citta' ritentino nello stesso
identico istante.

**Come si potrebbe verificare.** Contare i tentativi per esito nel manifest: le
righe con `stato_http` 4xx devono avere `tentativi` pari a 1.

---

### 17. I segnaposto in `config.yaml` impediscono l'avvio

**Decisione.** Il collector si rifiuta di partire se un indirizzo obbligatorio
inizia ancora con `INSERIRE_QUI_`, e riporta **tutti** i problemi trovati insieme,
non solo il primo.

**Alternative considerate.** Emettere un avviso e proseguire saltando le citta'
incomplete.

**Motivo.** L'errore piu' costoso possibile in questo progetto e' credere di
star raccogliendo e scoprire dopo tre giorni che non e' vero: quei giorni non
tornano. Un avvio rumorosamente fallito e' preferibile a una raccolta
silenziosamente vuota. L'accumulo dei problemi serve a chi compila il file la
prima volta, che altrimenti li scoprirebbe uno per volta.

**Come si potrebbe verificare.** `--verifica-config` su un file con segnaposto
deve uscire con codice 2 e nominare ogni campo mancante.

---

### 18. Interrogazione sequenziale delle citta'

**Decisione.** Le citta' vengono interrogate una dopo l'altra nello stesso
thread.

**Alternative considerate.** Un pool di thread per interrogarle in parallelo.

**Motivo.** Con due o tre citta' e un timeout di 20 s, il caso peggiore resta
ampiamente dentro l'intervallo di 60 s, e il codice sequenziale non ha stato
condiviso da proteggere: e' piu' semplice da leggere, da collaudare e da
motivare. Il parallelismo si giustificherebbe solo con molte piu' citta'.

**Come si potrebbe verificare.** Misurare la durata dei giri sul manifest. Se il
log iniziasse a riportare tick saltati, il sequenziale non basterebbe piu'.

---

### 19. Ripiego sul fuso di sistema quando il fuso IANA non e' disponibile

**Decisione.** Se `ZoneInfo` non riesce a risolvere il fuso configurato, il
collector emette un avviso e continua usando il fuso locale della macchina,
invece di interrompersi.

**Alternative considerate.** Considerarlo un errore fatale, per non produrre dati
con una data di servizio potenzialmente sbagliata.

**Motivo.** I due errori non sono simmetrici. Perdere ore di raccolta e' un danno
permanente; una data di servizio calcolata con il fuso sbagliato e' un errore
sistematico, visibile nel log e correggibile a posteriori perche' il manifest
conserva comunque l'istante UTC di ogni interrogazione.

**Come si potrebbe verificare.** Disinstallare `tzdata` in un venv di prova: la
raccolta deve proseguire con un avviso, e gli istanti UTC nel manifest devono
restare corretti.

---

### 20. Compito Windows autoriparante, in UTF-16 e con `UserId` esplicito

**Decisione.** L'esecuzione in background su Windows usa un compito
dell'Utilita' di pianificazione con trigger all'accesso, ripetizione ogni 5
minuti senza scadenza e `MultipleInstancesPolicy=IgnoreNew`.

**Alternative considerate.** Un semplice trigger all'avvio senza ripetizione;
oppure lasciare una finestra di terminale aperta.

**Motivo.** La combinazione ripetizione + `IgnoreNew` e' un meccanismo
autoriparante: finche' la raccolta e' viva il nuovo avvio viene ignorato, e
appena il processo muore per qualsiasi motivo il tentativo successivo lo fa
ripartire entro cinque minuti. Servono inoltre `ExecutionTimeLimit=PT0S` (il
valore predefinito di Windows terminerebbe il processo dopo 3 giorni, nel bel
mezzo della campagna) e le due opzioni sulle batterie disattivate (su un
portatile la raccolta si fermerebbe staccando l'alimentatore).

Due dettagli sono stati scoperti provando davvero a importare il compito, non
dedotti: **`schtasks` rifiuta un XML in UTF-8** con l'errore "impossibile passare
a un'altra codifica", quindi il file deve restare in UTF-16 (ed e' marcato
`-text` in `.gitattributes` perche' git non lo normalizzi); e **senza l'elemento
`<UserId>`** in `<Principal>` e in `<LogonTrigger>` la creazione fallisce con
"Accesso negato". Il compito e' stato creato ed eliminato con successo su questa
macchina come verifica.

**Come si potrebbe verificare.** Terminare a mano il processo di raccolta e
controllare che entro cinque minuti ne compaia uno nuovo, con la continuita' del
manifest a confermarlo.

---

### 21. Dipendenze esterne iniettate come parametri, mai catturate come default

**Decisione.** Rete, attesa e casualita' sono parametri delle funzioni che le
usano (`apri`, `dormi`, `casuale`, `esiste`), risolti **dentro** il corpo quando
valgono `None`.

**Alternative considerate.** Usarle direttamente, e nei test sostituire l'intero
modulo con `monkeypatch`.

**Motivo.** E' cio' che rende collaudabile la logica senza toccare la rete e
senza attese reali: i test verificano che un 404 non venga ritentato e che le
attese fra tentativi crescano, in millisecondi. La risoluzione dentro il corpo
invece che come valore predefinito del parametro non e' un dettaglio stilistico:
un default valutato alla definizione catturerebbe per sempre la funzione
originale, rendendo impossibile sostituirla dall'esterno. Il collector aveva
inizialmente `apri=urllib.request.urlopen` come default ed e' stato corretto
proprio per questo.

**Come si potrebbe verificare.** I 46 test della Fase 0 girano in circa 5 secondi
e senza rete esterna. Se un test iniziasse a fallire per indisponibilita' di un
servizio, l'iniezione non starebbe piu' funzionando.

---

## Fase 0-bis — Correzioni dopo la configurazione dei feed reali

### 22. I feed di Torino sono in HTTPS, non in HTTP

**Decisione.** Gli indirizzi GTT in `config.yaml` usano `https://`.

**Alternative considerate.** Usare gli indirizzi `http://` come inizialmente
indicati, adattando il collector a tollerare il traffico in chiaro.

**Motivo.** Gli indirizzi in `http://` **non sono raggiungibili**. Verificato il
2026-08-25: il nome `percorsieorari.gtt.to.it` risolve correttamente
(89.184.107.11), ma la connessione TCP sulla porta 80 scade dopo ~15 s, mentre
sulla porta 443 si stabilisce in 0,1 s. Non e' un blocco locale della porta 80:
nello stesso momento `example.com:80` risponde istantaneamente. Con `http://`
entrambi i feed fallivano con `timed out`; con `https://` restituiscono 382
entita' e 2.190 `stop_time_update`, di cui 1.420 con il campo `delay` e 770 con
l'orario assoluto.

**Come si potrebbe verificare.** `python scripts/verifica_feed.py --citta torino`
deve chiudere con esito OK su entrambi i feed. Un ritorno a `http://`
riprodurrebbe il timeout.

---

### 23. L'orario statico si confronta tramite il file `.md5`, non riscaricandolo

**Decisione.** Il controllo giornaliero scarica prima il file `.md5` pubblicato
accanto all'archivio e, se l'impronta coincide con quella gia' archiviata, non
scarica nulla e registra solo un marcatore. Quando il `.md5` manca (Torino) o non
e' raggiungibile, si ripiega sullo scaricamento dell'archivio e sul confronto
della sua impronta. Sostituisce il meccanismo SHA-256 della voce 14.

**Alternative considerate.** Scaricare ogni giorno l'intero archivio e
confrontarne l'impronta, come faceva la versione precedente; oppure fidarsi
dell'intestazione HTTP `Last-Modified`.

**Motivo.** L'archivio di Roma pesa **48,5 MB** e cambia quasi ogni giorno.
Scaricarlo per scoprire che non e' cambiato costerebbe 48 MB al giorno di banda
per nulla; il `.md5` ne costa 59. `Last-Modified` e' stato scartato perche' molti
server lo aggiornano a ogni rigenerazione anche quando il contenuto e' identico,
quindi non distinguerebbe una revisione vera da una ripubblicazione. La scelta di
MD5 non e' crittografica ma di interoperabilita': e' l'impronta che l'agenzia
pubblica, e usarne un'altra renderebbe impossibile il confronto senza scaricare.

**Aggiornamento: la frequenza di cambiamento e' stata misurata.** Sui **quindici
giorni mappati** fra il 25 agosto e l'8 settembre, **Roma ha prodotto quindici
revisioni distinte su quindici giorni**, cioe' cambia archivio ogni giorno **senza
una sola eccezione**, e **Torino cinque su quindici**, cioe' esattamente una ogni
tre. Il primo cambiamento di Torino, fra il 25 e il 26 agosto, portava l'archivio
da **19.905.201 a 20.264.224 byte**. La formulazione corretta
non e' quindi che Roma aggiorna l'orario e Torino no, ma che **entrambe lo
aggiornano con frequenza diversa**, ed e' una versione piu' forte della
motivazione: se l'archivio fosse stato scaricato una volta sola, per esempio il 27
agosto, i dump del 25 sarebbero associati all'orario sbagliato **per entrambe le
citta'**, non per la sola Roma.

**Come si potrebbe verificare.** Il test
`test_se_il_md5_e_invariato_l_archivio_non_viene_scaricato` controlla che nei
giorni senza modifiche l'indirizzo dell'archivio non venga mai interrogato. Sul
campo: in `logs/collector.log`, le righe "orario statico invariato" non devono
essere accompagnate da 48 MB di traffico.

---

### 24. `index.json` mappa ogni data alla versione dell'orario valida quel giorno

**Decisione.** Ogni citta' ha `data/raw/gtfs/<citta>/index.json` con due sezioni:
`giorni`, che associa ogni data di servizio al file dell'orario in vigore quel
giorno, e `versioni`, che elenca le revisioni distinte con la loro impronta. Nei
giorni senza modifiche viene scritto solo un marcatore che punta all'archivio
precedente, senza duplicarlo.

**Alternative considerate.** Dedurre la versione valida dal nome dei file
archiviati, ordinandoli per data.

**Motivo.** La deduzione dai nomi funziona finche' non ci sono buchi. Ma il
collector puo' restare fermo per giorni, e in quel caso non esiste alcun file per
le date scoperte: senza una mappa esplicita la Fase 3 dovrebbe reimplementare la
regola "vale l'ultima revisione precedente", che e' esattamente il genere di
logica che non si vuole duplicare in due punti. La funzione `versione_valida`
implementa quella regola una volta sola, con i suoi test.

**Come si potrebbe verificare.** In Fase 3, misurare la quota di
`(trip_id, service_date)` del real-time che trova corrispondenza nell'orario
indicato da `index.json` per quel giorno. Deve restare vicina al 100% anche a
cavallo di una revisione.

---

### 25. Registro delle interruzioni in `gaps.jsonl`

**Decisione.** Ogni citta' ha `data/raw/rt/<citta>/gaps.jsonl`, una riga JSON per
ogni finestra senza raccolta, con inizio, fine, durata e causa. Le cause sono
`processo_non_attivo` (rilevata al riavvio confrontando l'istante corrente con il
battito lasciato dal processo precedente) e `errori_di_rete_prolungati` (nessun
feed raggiungibile per oltre `soglia_interruzione_secondi`, predefinito 300 s).

**Alternative considerate.** Ricostruire le interruzioni a posteriori dai buchi
nel manifest giornaliero.

**Motivo.** Dal manifest si vede l'assenza di righe, ma non se ne conosce la
causa, e soprattutto non si distingue "il collector era spento" da "il collector
girava e il feed non rispondeva": sono due situazioni diverse per il backtesting.
Senza questa distinzione, una coincidenza che risulta persa potrebbe essere
semplicemente una coincidenza mai osservata, e la valutazione sperimentale ne
uscirebbe falsata in un modo non rilevabile a posteriori.

La finestra viene scritta solo quando si **richiude**, perche' prima non se ne
conosce la fine; se il processo muore mentre una finestra e' aperta, il battito
su disco resta fermo all'ultimo successo e sara' l'avvio successivo a
registrarla. E' il motivo per cui il battito viene aggiornato solo sui giri
riusciti.

La soglia di 300 s (cinque tick) esiste per non trasformare ogni errore isolato
in una riga: un tick perso e recuperato subito e' rumore, non un buco nei dati.

**Aggiornamento: la distinzione si e' manifestata sul campo.** Il 27 agosto e'
comparsa la prima interruzione con causa `errori_di_rete_prolungati`: **32 minuti
su Torino**, mentre Roma raccoglieva regolarmente. Tutte le precedenti avevano
causa `processo_non_attivo`. La contemporaneita' e' essa stessa la prova che la
causa e' corretta: se fosse stato il collector a fermarsi, si sarebbero fermate
entrambe le citta'.

La conseguenza per la Fase 3 va fissata ora, perche' a posteriori il dato non e'
piu' ricostruibile. Con `processo_non_attivo` l'informazione **esisteva** e non
l'abbiamo raccolta, quindi quei minuti vanno esclusi dal backtesting: altrimenti
una coincidenza mai osservata verrebbe scambiata per una coincidenza persa. Con
`errori_di_rete_prolungati` l'informazione **non era disponibile nemmeno a un
passeggero reale**: e' una condizione del mondo e non una lacuna della raccolta, e
un pianificatore che in quel momento avesse dovuto decidere si sarebbe trovato
senza dati esattamente come noi. Escludere anche quelle finestre toglierebbe dal
campione proprio i momenti in cui il problema e' piu' difficile.

**Come si potrebbe verificare.** Terminare il collector, attendere dieci minuti e
riavviarlo: deve comparire una riga con causa `processo_non_attivo` e durata pari
all'attesa. La somma delle durate in `gaps.jsonl`, rapportata al periodo di
raccolta, e' la copertura da dichiarare nella documentazione.

---

### 26. Gli indirizzi in chiaro sono ammessi, le credenziali in chiaro no

**Decisione.** Un feed servito in `http://` viene accettato, ma segnalato
all'avvio e in `--verifica-config`. Se pero' la stessa citta' dichiara delle
`intestazioni_http` non vuote, la configurazione viene **rifiutata**.

**Alternative considerate.** Rifiutare qualunque indirizzo non cifrato; oppure
accettarlo senza dire nulla.

**Motivo.** Rifiutare del tutto significherebbe rinunciare in partenza a
un'agenzia che pubblichi solo in chiaro, e i dati di un feed di trasporto
pubblico sono pubblici per definizione: il rischio e' la manomissione lungo il
percorso, non la riservatezza. Le credenziali sono un altro discorso: una chiave
d'accesso spedita in chiaro per settimane e' un regalo alla rete, e un rifiuto
all'avvio costa molto meno che accorgersene dopo. Nella configurazione attuale
nessun indirizzo e' in chiaro (vedere voce 22), ma il controllo resta perche' la
prossima agenzia potrebbe esserlo.

**Come si potrebbe verificare.** Il test
`test_credenziali_su_http_sono_rifiutate` copre il caso; `--verifica-config`
elenca gli indirizzi non cifrati.

---

### 27. Uno script di verifica separato dal collector

**Decisione.** `scripts/verifica_feed.py` scarica una volta ogni feed
configurato, lo decodifica **contando le entita' per conto proprio** invece di
riusare il riepilogo del collector, e stampa un esempio decodificato.

**Alternative considerate.** Usare solo `--diagnostica` del collector, che fa
qualcosa di simile.

**Motivo.** Il doppio conteggio e' voluto: se il numero prodotto dallo script e
quello prodotto dal collector divergessero, sarebbe il segnale che il parser del
collector sta contando qualcosa di diverso da quello che crediamo. Un errore di
quel tipo, scoperto in Fase 3, invaliderebbe settimane di dati. L'esempio
decodificato serve a capire come la singola agenzia popola i campi, cosa che i
conteggi non dicono: e' cosi' che si e' visto che Torino fornisce `delay` su
1.420 passaggi ma l'orario assoluto solo su 770, e che nei `trip_update` di
Torino manca il `route_id`, presente invece nei `vehicle_positions`, che quindi
in Fase 3 andra' recuperato dall'orario statico.

Il giudizio e' differenziato per tipo di feed: un `vehicle_positions` non
contiene TripUpdate per definizione, e giudicarlo con il metro dei `trip_updates`
lo dichiarerebbe inutilizzabile proprio quando funziona come deve. La prima
versione dello script aveva questo difetto ed e' stata corretta.

**Come si potrebbe verificare.** `python scripts/verifica_feed.py` deve chiudere
con codice 0 e "Tutti i feed configurati sono utilizzabili".

---

### 28. Volume misurato della raccolta

**Decisione.** Si conferma il salvataggio non compresso deciso alla voce 7, ma il
numero che li' mancava ora e' misurato.

**Motivo.** Un giro completo (2 citta' x 2 feed) pesa **910 KB**: Roma 735 KB di
`trip_updates` e 100 KB di `vehicle_positions`, Torino 66 KB e 28 KB. A 1440 giri
al giorno la proiezione **grezza** e' di **1,34 GB al giorno**, cioe' circa
**40 GB su 30 giorni**, prima della deduplica. Su 565 GB liberi resta ampiamente
sostenibile, ma non e' trascurabile: e' l'ordine di grandezza che rende
obbligatoria una copia di sicurezza fuori dal disco di lavoro.

L'archivio statico di Roma pesa 48,5 MB per revisione; con un cambio quasi
quotidiano, sono circa 1,5 GB al mese in piu'.

**Come si potrebbe verificare.** Dopo il primo giorno pieno, confrontare
l'occupazione reale con la proiezione: la differenza misura il risparmio della
deduplica per `header.timestamp`. Se l'occupazione reale superasse i 2 GB al
giorno, la compressione scartata alla voce 7 andrebbe riconsiderata.

---

### 29. Nessun dato raccolto da scartare

**Decisione.** La cartella `data/raw/_scartato/` non e' stata creata, perche' non
c'era nulla da spostarci.

**Motivo.** Al momento della richiesta di correzione (2026-08-25) lo stato
verificato era: nessun processo Python attivo, nessun compito pianificato
registrato, `logs/collector.log` di 0 byte, `data/raw/` contenente i soli file
`.gitkeep`, e `config.yaml` ancora pieno di segnaposto `INSERIRE_QUI_` che il
validatore rifiuta all'avvio. La raccolta non era quindi mai partita. Va aggiunto
che il collector non ha mai gestito i feed *service alerts*: i tipi supportati
sono sempre stati solo `trip_updates` e `vehicle_positions`, quindi non avrebbe
potuto raccogliere avvisi testuali nemmeno con gli indirizzi sbagliati.

**Come si potrebbe verificare.** `git log` mostra che `config.yaml` e' passato
dai segnaposto agli indirizzi reali in un unico commit, senza raccolte
intermedie; il primo `_manifest.csv` presente su disco e' del 2026-08-25.

---

## Fase 1 — GTFS statico e base di conoscenza

### 30. Indice spaziale a griglia per la regola del cammino

**Decisione.** La regola del trasbordo a piedi confronta soltanto le fermate che
si trovano nella stessa cella di una griglia regolare o in una delle otto
adiacenti. Il lato della cella e' posto **uguale** alla soglia di cammino, non e'
un parametro indipendente.

**Alternative considerate.** Confrontare tutte le coppie di fermate; oppure
precalcolare le distanze in Python e passarle come fatti.

**Motivo.** Il confronto esaustivo istanzia un numero quadratico di atomi: sulle
8.301 fermate di Roma sono circa 69 milioni di coppie, e il grounding non termina
in tempo utile. Precalcolare le distanze in Python era l'altra via, ma avrebbe
spostato fuori dalla base di conoscenza proprio la regola che decide quali coppie
siano trasbordi, riducendo la KB a un'interrogazione su una tabella gia'
calcolata: esattamente cio' che il progetto deve evitare.

Il vincolo lato = soglia e' cio' che rende l'indice **semanticamente neutro**: due
fermate a distanza inferiore alla soglia non possono cadere in celle non
adiacenti, quindi nessun trasbordo puo' sfuggire al confronto. Un lato piu'
piccolo romperebbe la garanzia.

Va dichiarato che non si tratta di clustering nel senso escluso dai vincoli di
valutazione: non c'e' nulla di appreso, nessun centroide, nessuna funzione
obiettivo, nessuna dipendenza dai dati oltre le coordinate. E' un'indicizzazione
deterministica, l'equivalente spaziale di un indice su una colonna.

**Come si potrebbe verificare.** E' stato verificato in due modi. Il test
`test_l_indice_spaziale_non_altera_i_trasbordi_derivati` confronta gli insiemi
derivati con e senza indice sul GTFS giocattolo; la misura di complessita' ripete
il confronto sui dati reali a 50, 150 e 400 fermate per entrambe le citta'. In
tutti i casi gli insiemi sono risultati identici. Il risparmio misurato cresce da
1,4 a 10,1 volte nell'intervallo esaminato.

---

### 31. Identificativi interi e coordinate in metri

**Decisione.** Gli identificativi GTFS delle fermate diventano interi progressivi
prima di entrare nel programma logico, e le coordinate geografiche diventano metri
interi su una proiezione equirettangolare locale centrata sul baricentro delle
fermate della citta'.

**Alternative considerate.** Usare gli identificativi testuali come costanti ASP e
le coordinate in micro-gradi, calcolando il fattore di conversione dentro la
regola.

**Motivo.** Sono entrambi cambi di rappresentazione, non di conoscenza: la
corrispondenza fra identificativi e' biunivoca e viene conservata in memoria, e la
proiezione e' un cambio di unita' di misura, l'analogo del conservare gli orari in
secondi anziche' come `HH:MM:SS`. Il guadagno sugli identificativi e' di velocita'
nel grounding. Sulle coordinate il guadagno e' che la regola di distanza puo'
essere scritta in aritmetica intera semplice, senza dover conoscere la latitudine:
in gradi il rapporto fra un grado di longitudine e uno di latitudine dipende dal
coseno della latitudine, e portarlo dentro la regola avrebbe richiesto una
costante precalcolata comunque, con in piu' l'illeggibilita'.

L'errore della proiezione equirettangolare, sulla scala di una citta' e a
distanze dell'ordine dei 250 metri, e' inferiore al metro: irrilevante rispetto
alla discretizzazione in bande decisa alla voce 32.

**Come si potrebbe verificare.** Confrontare, su un campione di coppie, la
distanza calcolata sul piano proiettato con la distanza geodetica: lo scarto deve
restare sotto il metro alle distanze rilevanti.

---

### 32. Tempo di cammino discretizzato in bande

**Decisione.** Il tempo di cammino non e' proporzionale alla distanza ma assume
quattro valori, secondo la banda di distanza in cui la coppia ricade. La regola
seleziona il minimo fra i tempi delle bande che contengono la distanza, usando un
aggregato `#min`.

**Alternative considerate.** Calcolare la radice quadrata della distanza al
quadrato e dividere per una velocita'.

**Motivo.** In aritmetica intera la radice quadrata si esprime generando un
candidato per ogni valore possibile e vincolandolo, il che moltiplicherebbe il
grounding per il numero di metri della soglia: 251 istanze per ogni coppia
candidata, cioe' due ordini di grandezza di costo in piu' per una precisione che
non serve. Un tempo di trasbordo ha senso al mezzo minuto, non al metro.

E' una scelta di modello dichiarata, non un'approssimazione subita, e resta
interna alla base di conoscenza: le bande sono fatti ASP, e cambiarle significa
cambiare quattro righe di `rules.lp`.

**Come si potrebbe verificare.** Raffinare le bande a passi di 25 metri e
misurare quanto cambino i tempi minimi derivati e il costo di grounding. Se i
tempi cambiassero in modo apprezzabile, la discretizzazione sarebbe troppo
grossolana.

---

### 33. Campionamento per prossimita' dal baricentro geometrico

**Decisione.** Le sottoreti della curva di complessita' sono le N fermate piu'
vicine a un centro fisso, e il centro e' la fermata piu' vicina al baricentro
geometrico di tutte le fermate della citta', calcolato dai dati.

**Alternative considerate.** Campionamento casuale uniforme; oppure un centro
scelto a mano, per esempio la stazione principale.

**Motivo.** Cinquanta fermate estratte a sorte fra le 8.301 di Roma finirebbero
sparse su tutta la citta', a chilometri l'una dall'altra, e non genererebbero
quasi nessun trasbordo a piedi: la curva misurerebbe il costo di un problema che
non somiglia a quello vero. Il campionamento per prossimita' conserva la densita'
reale della rete. Ha inoltre la proprieta' di essere monotono, cioe' un campione
piu' grande contiene quello piu' piccolo, senza la quale i punti della curva non
sarebbero confrontabili fra loro.

Il centro derivato dai dati anziche' scelto a mano rende la misura riproducibile e
dichiarabile: per Roma e' la fermata 70841, S. SABA/AVENTINO, per Torino la 962,
Fermata 1873 - PUGLIA C.3.

Il limite va dichiarato: i risultati valgono per porzioni connesse e dense di
rete e non sono estrapolabili a un campione sparso di pari cardinalita'. La
misura sull'intera rete lo conferma, perche' produce meno atomi di quanti la
curva ne avrebbe fatti prevedere.

**Come si potrebbe verificare.** Ripetere la curva con campionamento casuale: ci
si attende un numero di trasbordi per fermata molto piu' basso e una crescita
degli atomi quasi lineare, perche' la chiusura transitiva non troverebbe
componenti connesse di dimensione apprezzabile.

---

### 34. Vincoli di integrita' scelti perche' possano essere violati

**Decisione.** Dei vincoli inizialmente formulati ne sono stati mantenuti quattro
e scartati due. Gli scartati vietavano il trasbordo di una fermata con se stessa e
imponevano la simmetria del cammino.

**Alternative considerate.** Tenerli tutti, dato che non costano nulla.

**Motivo.** La costruzione della regola `candidata` rende quei due vincoli
impossibili da violare per definizione: nessun dato, per quanto malformato, puo'
farli scattare. Un vincolo che non puo' mai essere violato non e' logica, e'
commento travestito da logica, e in sede d'esame sarebbe un punto debole invece
che un punto di forza. I quattro mantenuti corrispondono ciascuno a un difetto
documentato dei GTFS pubblicati: grado implausibile per coordinate mancanti, tempo
dichiarato piu' breve del cammino, banchina accessibile in stazione non
accessibile, tempo di trasbordo nullo.

**Come si potrebbe verificare.** Ciascuno dei quattro ha un test che costruisce il
dato che lo viola e verifica che il programma diventi insoddisfacibile, e che
torni soddisfacibile disattivando i soli vincoli. I due scartati non sarebbero
collaudabili in questo modo, ed e' precisamente la ragione per cui sono stati
tolti.

---

### 35. La materializzazione per la Fase 2 escludera' la chiusura transitiva

**Decisione.** `transfers.parquet` contiene la relazione `trasbordo_ammissibile`
con i suoi attributi, non la chiusura `raggiungibile`. La chiusura resta
calcolabile su richiesta, tramite un interruttore del programma logico.

**Alternative considerate.** Materializzare anche la chiusura, dato che il grafo
tempo-espanso potrebbe volerla.

**Motivo.** La misura di complessita' mostra che la chiusura transitiva genera fra
il 70% e il 93% degli atomi alle dimensioni maggiori, mentre la relazione
effettivamente consumata dal grafo tempo-espanso e' quella dei trasbordi diretti,
che cresce linearmente e si attesta su circa cinque trasbordi per fermata a Roma e
tre a Torino. Materializzare la chiusura costerebbe un ordine di grandezza in piu'
per rispondere a domande che il pianificatore pone di rado.

Il fatto che la scelta si possa compiere a valle, disattivando un interruttore
invece di riformulare le regole, e' una conseguenza diretta della natura
dichiarativa della rappresentazione.

**Come si potrebbe verificare.** In Fase 2, contare quante volte il grafo
tempo-espanso interroghi effettivamente la raggiungibilita' globale. Se il numero
fosse alto, converrebbe materializzarla.

---

### 36. Risultato negativo: Roma non dichiara accessibilita' ne' stazioni

**Decisione.** Le regole sull'accessibilita' e il livello di stazione della
gerarchia dei tempi restano nella base di conoscenza, pur non ricevendo fatti
utili da Roma.

**Motivo.** Verificato sui dati del 2026-08-26: tutte le 8.301 fermate di Roma
dichiarano `wheelchair_boarding` uguale a zero, cioe' "informazione non
disponibile", e lo stesso vale per tutte le 179.177 corse; nessuna fermata di
Roma dichiara una `parent_station`. La conseguenza e' che sull'intera rete di
Roma la base di conoscenza deriva **zero** trasbordi accessibili. Torino si
comporta diversamente: 2.722 fermate accessibili, 1.075 esplicitamente non
accessibili, e 7.382 trasbordi accessibili derivati su 21.130; ma anche li'
soltanto due fermate su 7.073 appartengono a una stazione.

Sommato al fatto che nessuna delle due citta' pubblica `transfers.txt`, questo
significa che l'eredita' difettibile a tre livelli, sul campo, opera quasi
ovunque sul solo terzo livello. Le regole restano perche' la base di conoscenza e'
scritta per il formato GTFS e non per due archivi particolari, e su un'azienda
che pubblichi quei campi entrerebbero in funzione senza modifiche; ma sarebbe
disonesto presentarle come funzionanti su questi dati, e vengono percio' dichiarate
come tali nel documento.

**Conseguenza operativa.** Ogni risultato sull'accessibilita' nelle fasi
successive andra' riferito alla sola Torino, mai alla media delle due citta'.

**Come si potrebbe verificare.** Aggiungere al progetto una terza citta' che
pubblichi `transfers.txt` e una gerarchia di stazioni, e osservare che i primi due
livelli della gerarchia entrino in funzione senza modificare `rules.lp`.

---

## Fase 0-quater — Spostamento della raccolta su VM

### 37. La raccolta si sposta su una VM sempre accesa

**Decisione.** Il collector gira su una VM Oracle Ubuntu 24.04 aarch64 e non piu'
sul PC di lavoro. La VM esegue **soltanto** la raccolta e il consolidamento
notturno; esperimenti, test e scrittura del documento restano sul PC.

**Alternative considerate.** Tenere la raccolta sul PC configurando il risparmio
energetico perche' non vada mai in sospensione.

**Motivo.** La copertura reale misurata sul PC e' stata del **7,2%**: in ventidue
ore di calendario, novantacinque giri su millecentoventidue attesi, con 20,4 ore
registrate in `gaps.jsonl` come interruzioni. La causa non era il software ma la
macchina, che si spegne e si sospende. Configurare il risparmio energetico
avrebbe risolto il caso della sospensione ma non quello dello spegnimento
volontario, e avrebbe legato la campagna sperimentale all'abitudine di non
spegnere il computer per due settimane.

La divisione dei ruoli e' altrettanto deliberata. Duplicare l'ambiente completo
sulla VM avrebbe significato installare `clingo`, `scikit-learn`, `matplotlib`,
`scipy` e `pytest` su una macchina che non li usa, e soprattutto avrebbe creato
un secondo posto in cui gli esperimenti possono essere eseguiti, con il rischio
di risultati prodotti su due macchine diverse e non confrontabili.

**Divergenza fra i due ambienti, dichiarata.** La VM usa CPython 3.12 su aarch64,
il PC CPython 3.14.6 su x86-64. Le **versioni dei pacchetti sono identiche**
(vedere la voce 38), quindi la divergenza si riduce alla versione minore
dell'interprete e all'architettura. Nessun risultato sperimentale viene prodotto
sulla VM: la VM raccoglie e consolida, cioe' esegue trasformazioni deterministiche
di formato, mentre ogni numero che finisce nel documento e' calcolato sul PC. La
riproducibilita' resta percio' intatta.

**Come si potrebbe verificare.** Confrontare la copertura reale calcolata da
`deploy/stato.sh` prima e dopo lo spostamento. Sul PC era del 7,2%; sulla VM deve
restare vicina al 100% salvo interruzioni dichiarate in `gaps.jsonl`.

---

### 38. Dipendenze della VM: sottoinsieme, ma versioni identiche

**Decisione.** `deploy/requirements-collector.txt` elenca sei pacchetti invece di
dodici, con le **stesse versioni esatte** di `requirements.txt`.

**Alternative considerate.** Riusare `requirements.txt` per intero; oppure
allentare i vincoli di versione se qualcuno non fosse esistito per aarch64.

**Motivo.** Il collector importa dalla libreria standard piu' `yaml` e
`google.transit`; il consolidamento aggiunge `pandas`, `pyarrow` e `numpy`. Il
resto non serve. Prima di scrivere qualunque cosa e' stato verificato, con una
risoluzione mirata alla piattaforma di destinazione, che tutte e sei le versioni
esistano come wheel `cp312` per `manylinux aarch64`: PyYAML e protobuf su
`manylinux2014`, pandas su `manylinux_2_24`, numpy su `manylinux_2_27`, pyarrow
su `manylinux_2_28`, gtfs-realtime-bindings come pacchetto puro. Il tag piu'
restrittivo richiede glibc 2.28 e Ubuntu 24.04 ne ha la 2.39.

Non e' stato necessario allentare alcun vincolo, che era l'esito che rischiava di
compromettere la riproducibilita'. E' stata inoltre verificata la compatibilita'
sintattica dei moduli che girano sulla VM con Python 3.12 e 3.11, dato che sono
stati scritti su 3.14.

**Come si potrebbe verificare.** Ripetere `pip install --dry-run
--only-binary=:all:` con i flag di piattaforma. Se una wheel sparisse dall'indice
il comando fallirebbe subito invece di ripiegare su una compilazione.

---

### 39. L'indirizzo della VM sta in `~/.ssh/config`, non in un file del progetto

**Decisione.** Gli script usano l'alias ssh `vm-icon`. Indirizzo e chiave stanno
nella configurazione ssh dell'utente, fuori dal repository.

**Alternative considerate.** Un file `deploy/vm.env` con `VM_HOST` e `VM_KEY`,
escluso da git tramite `.gitignore`.

**Motivo.** Il repository viene consegnato al docente, quindi ne' l'indirizzo
della VM ne' alcuna chiave devono poterci finire. Con `vm.env` la protezione
dipende interamente dal `.gitignore`: basta un `git add -f` distratto, o
l'invio di un archivio compresso della cartella, e il segreto esce. Con la
configurazione ssh il file sta altrove, quindi **il rischio non esiste per
costruzione** invece di essere mitigato. In piu' l'alias funziona identico per
`ssh`, `scp` e `rsync`, mentre `vm.env` avrebbe richiesto a ogni script di
comporre le opzioni a mano.

`deploy/vm.env` resta comunque nel `.gitignore` come rete di sicurezza.

**Come si potrebbe verificare.** Una ricerca di indirizzi IP e di materiale di
chiave su `deploy/` non deve trovare nulla. Gli script che non trovano l'alias
configurato si fermano stampando il blocco da incollare, senza tentare
connessioni verso un host vuoto.

---

### 40. Sincronizzazione senza rsync

**Decisione.** `deploy/sync.sh` usa `rsync` se lo trova nel PATH e altrimenti
ripiega su `tar` attraverso `ssh`.

**Alternative considerate.** Richiedere l'installazione di rsync da MSYS2;
oppure usare `scp -r` ritrasferendo tutto ogni volta.

**Motivo.** E' stato verificato che `rsync` non esiste in Git Bash e non e'
presente nemmeno nell'installazione MSYS2 sulla macchina: uno script scritto
attorno a rsync sarebbe fallito al primo lancio. Chiedere di installarlo per un
solo comando non e' proporzionato.

L'incrementalita' non si perde, e la ragione e' architetturale piu' che
implementativa. Il payload predefinito - archivi statici, `index.json`, manifest,
`gaps.jsonl`, parquet - pesa pochi MB e si trasferisce per intero in pochi
secondi, quindi distinguere il gia'-presente costerebbe piu' del trasferimento.
I dump grezzi, dopo il consolidamento, diventano archivi giornalieri
**immutabili**: un giorno chiuso non cambia mai piu', quindi basta scaricare i
file che non si hanno gia', e lo script li confronta per nome prima di chiederli.

**Come si potrebbe verificare.** Eseguire `sync.sh --grezzi` due volte di
seguito: la seconda non deve trasferire alcun archivio giornaliero.

---

### 41. Deduplica delle osservazioni, e il risultato negativo che l'accompagna

**Decisione.** Per ogni passaggio, identificato da `(trip_id, stop_sequence)`, si
conserva una riga a ogni **cambio** del valore osservato, con il `timestamp_feed`
della prima comparsa di quel valore. Sono disponibili due politiche alternative,
`ultimo` e `fasce`.

**Alternative considerate.** Una riga per passaggio, conservando solo l'ultima
osservazione; oppure una riga per ogni dump, senza alcuna deduplica.

**Motivo.** Una previsione che cambia nel corso della giornata **non e' un
duplicato**: e' l'evoluzione della stima dell'azienda, e dice quanto quella
previsione fosse affidabile con un certo anticipo. E' informazione che in Fase 3
potremmo voler usare come variabile esplicativa, e che non e' ricostruibile a
posteriori se la si getta ora. Conservare solo l'ultimo valore distruggerebbe un
dato irripetibile; conservare una riga per dump conserverebbe soprattutto
ripetizioni.

L'implementazione registra i cambi anziche' i valori distinti in senso
insiemistico. La differenza si vede solo quando una previsione torna a un valore
gia' visto: in quel caso la ricomparsa viene conservata come evento a se'. E'
voluto, perche' un'oscillazione e' informazione sulla stabilita' della stima, e
perche' riconoscere i valori gia' visti richiederebbe di tenere in memoria
l'intero insieme dei valori di ogni passaggio, che su Roma significa decine di
milioni di voci.

**Il risultato negativo.** Il presupposto della regola era che lo stesso
passaggio comparisse identico in centinaia di dump consecutivi, e che la
deduplica scartasse quindi la quasi totalita' delle righe. **Misurato sui dati
reali, non e' cosi'.** Su 98 dump di Roma, 1.982.754 `stop_time_update` hanno
prodotto 1.361.088 righe, cioe' il **68,6%** del totale: Roma ricalcola la
previsione quasi a ogni giro, e ogni passaggio riceve in media 10,9 valori
distinti, fino a un massimo di 76. Su Torino la quota e' il 65,1% con 5,4 valori
per passaggio. La proiezione a giornata piena e' di circa **20 milioni di righe
al giorno per Roma** e 2,2 milioni per Torino, quindi dell'ordine dei 280 milioni
di righe su due settimane.

La regola resta quella scelta, perche' la motivazione che la giustifica non e'
il risparmio ma la conservazione di un'informazione irripetibile. Va pero'
registrato che il beneficio in volume che le era stato attribuito non si e'
verificato, e che il dimensionamento della Fase 3 va fatto su questi numeri e non
su quelli attesi. Le politiche `ultimo` e `fasce` esistono proprio per poter
cambiare idea sulla base di una misura invece che di una previsione.

**Come si potrebbe verificare.** Confrontare, in Fase 3, la qualita' del modello
addestrato sui dati completi con quella ottenuta usando la sola ultima
osservazione per passaggio. Se la differenza fosse trascurabile, la politica
`ultimo` sarebbe preferibile e ridurrebbe il dataset di un ordine di grandezza.

---

### 42. Torino non trasmette lo `stop_id`: la chiave di join e' `(trip_id, stop_sequence)`

**Decisione.** L'orario programmato si interroga con la chiave
`(trip_id, stop_sequence)`, e lo `stop_id` mancante viene riempito dall'orario
statico.

**Alternative considerate.** La chiave naturale `(trip_id, stop_id,
stop_sequence)`, che era la prima implementazione.

**Motivo.** E' stato scoperto eseguendo il consolidamento sui dati veri e
notando che il numero di passaggi conservati non tornava: 4.691 invece dei 13.092
misurati. La causa e' che **GTT non include mai lo `stop_id`** nei
`stop_time_update`, identificando la fermata con il solo `stop_sequence`; Roma si
comporta all'opposto e lo fornisce sempre. Con la chiave naturale, il join su
Torino non trovava mai corrispondenza: la colonna `stop_id` restava vuota,
l'orario programmato nullo e il ritardo non calcolabile, e il parquet di Torino
sarebbe stato inutilizzabile in Fase 3 senza che nulla lo segnalasse.

La specifica GTFS garantisce che `stop_sequence` sia univoco dentro una corsa,
quindi la chiave ridotta e' altrettanto precisa e funziona su entrambe le
aziende. Quando il feed fornisce anche lo `stop_id` si usa quello del feed e si
verifica che coincida con quello statico; una divergenza viene contata e
segnalata, perche' significherebbe che la corsa in circolazione non e' quella che
l'orario descrive.

Lo stesso meccanismo copre il `route_id`, anch'esso assente nei `trip_update` di
Torino. Si potrebbe ricavarlo dai `vehicle_positions`, ma richiederebbe un
accoppiamento temporale fra due feed con timestamp diversi, mentre `trips.txt`
lo dichiara in modo esatto.

**Come si potrebbe verificare.** Dopo il consolidamento, il conteggio dei valori
vuoti nelle colonne `stop_id` e `route_id` deve essere zero per entrambe le
citta', e quello dei nulli in `orario_programmato` e `ritardo_secondi` pure. Sui
due giorni gia' consolidati e' cosi'.

---

## Fase 2 — Grafo tempo-espanso e ricerca

### 43. Il grafo copre una finestra temporale, non la giornata

**Decisione.** Il grafo tempo-espanso viene costruito sull'intervallo
`[partenza, partenza + orizzonte]`, con orizzonte predefinito di 120 minuti.

**Alternative considerate.** Costruire il grafo dell'intera giornata di servizio e
riusarlo per tutte le interrogazioni.

**Motivo.** L'orario di Roma contiene 5,6 milioni di passaggi al giorno. Il grafo
completo non e' un oggetto che si costruisca per rispondere a una singola
interrogazione, e riusarlo fra interrogazioni diverse non aiuterebbe, perche' la
Fase 5 eseguira' migliaia di interrogazioni con orari di partenza diversi. La
finestra e' anche cio' che una interrogazione usa davvero: nessuno accetta di
attendere quattro ore alla fermata.

Il limite va dichiarato come limite dei risultati e non come nota
implementativa: **la ricerca trova l'ottimo dentro la finestra**, e un itinerario
che richiedesse di attendere oltre l'orizzonte non verrebbe trovato affatto.

**Come si potrebbe verificare.** E' misurato su quante coppie origine-destinazione
dell'esperimento la finestra di due ore si riveli sufficiente. Le coppie non
risolte non vengono escluse dal campione: la loro percentuale e' essa stessa un
risultato, e toglierle darebbe una falsa impressione di completezza.

---

### 44. Lo stato si sdoppia in "a terra" e "a bordo"

**Decisione.** Lo stato della ricerca e' la terna `(fermata, istante, cambi)` piu'
l'informazione se ci si trovi a terra oppure a bordo di una corsa specifica.

**Alternative considerate.** La sola terna, come formulata inizialmente.

**Motivo.** La terna da sola non permette di contare correttamente i cambi.
Stando a una fermata a un dato istante, "restare a bordo" e "salire di nuovo"
sono indistinguibili se non si sa su quale corsa ci si trovi: un viaggiatore che
percorre dieci fermate senza scendere passerebbe per dieci stati che sembrano
altrettante salite, e la ricerca gli attribuirebbe dieci cambi. Il numero di
cambi e' uno dei tre criteri della ricerca multi-criterio, quindi l'errore
falserebbe l'intera frontiera di Pareto senza che nulla lo segnali.

Il cambio si conta alla salita e non alla discesa: contarlo alla discesa
addebiterebbe un cambio anche a chi scende semplicemente a destinazione.

**Come si potrebbe verificare.** Il test
`test_restare_a_bordo_non_conta_come_cambio` percorre una corsa che attraversa
piu' fermate e verifica che il conteggio resti a uno.

---

### 45. La chiave di stato a terra non contiene l'istante

**Decisione.** Uno stato a terra e' identificato dalla coppia `(fermata, cambi)`,
conservando l'istante di arrivo piu' precoce, e non dalla terna completa.

**Alternative considerate.** La lettura letterale della terna, che era
l'implementazione iniziale.

**Motivo.** E' una relazione di dominanza: trovarsi alla stessa fermata con lo
stesso numero di cambi ma **prima** e' sempre almeno altrettanto buono, perche'
ogni proseguimento disponibile a chi arriva tardi lo e' anche a chi arriva presto
- le corse partono agli stessi orari per entrambi - e attendere non costa nulla.
Gli stati con istante posteriore sono percio' dominati e possono essere eliminati
senza perdere soluzioni.

Il guadagno non e' marginale ed e' stato misurato: su una interrogazione di
Torino, la formulazione con l'istante nella chiave espandeva **6,4 milioni di
stati in 224 secondi**, quella con la chiave ridotta ne espande **45 mila in 0,7
secondi**, restituendo lo stesso orario di arrivo. Sono due ordini di grandezza,
e la differenza fra una ricerca utilizzabile e una che non lo e'.

Va sottolineato che non e' un'approssimazione: elimina stati dimostrabilmente
dominati, e l'ottimo resta garantito.

**Come si potrebbe verificare.** La coincidenza degli orari di arrivo prima e
dopo l'ottimizzazione, gia' osservata; e il test che confronta A* con una ricerca
esaustiva su istanze piccole, che continua a passare.

---

### 46. L'euristica usa il massimo VERO delle velocita', difetti dell'orario compresi

**Decisione.** La velocita' `V` dell'euristica geografica e' il massimo assoluto
misurato fra fermate consecutive sull'orario programmato, senza alcun taglio.

**Alternative considerate.** Un percentile alto, che sarebbe piu' rappresentativo
della fisica del problema; oppure l'esclusione degli archi anomali come dati
sporchi.

**Motivo.** L'ammissibilita' dell'euristica e' una delle poche proprieta' che il
progetto puo' **dimostrare formalmente**, ed e' cio' che garantisce che A*
restituisca l'ottimo. La dimostrazione richiede che `V` sia un limite superiore
alla velocita' di ogni spostamento **del grafo che stiamo cercando**, non della
realta' fisica: se la tabella oraria dichiara quattrocento metri in tre secondi,
allora in quel grafo quel movimento e' possibile, e `V` deve tenerne conto.

La misura mostra che questo accade davvero. Le velocita' fra fermate consecutive
hanno mediana di 16,4 km/h a Torino e 15,6 a Roma, valori perfettamente
plausibili, ma il massimo e' di **500,8 km/h a Torino e 297,1 a Roma**, con 135 e
1.063 archi rispettivamente sopra i 150 km/h. Caratterizzando gli archi anomali si
scopre che **il difetto non e' nelle coordinate ma negli orari**: le distanze sono
normali, dell'ordine dei 200-400 metri, ed e' la durata programmata a essere
assurda, tre secondi.

L'esclusione degli archi anomali e' stata scartata per una ragione precisa:
sposterebbe la garanzia da "vale sull'orario pubblicato" a "vale sull'orario che
abbiamo deciso noi", indebolendo proprio la parte piu' solida del progetto.

**Conseguenza, che e' un risultato negativo da riportare.** Con `V` cosi' grande
l'euristica vale quasi zero, e A* risparmia pochi punti percentuali di nodi
rispetto a Dijkstra, risultando anzi piu' lento in tempo di orologio perche'
calcolare l'euristica costa piu' dei nodi che fa evitare.

**Come si potrebbe verificare.** Il confronto e' misurato su cinquanta coppie per
citta' e riportato nella sezione della documentazione. Un test verifica inoltre
per campionamento che l'euristica non superi mai il costo residuo reale.

---

### 47. Una variante non ammissibile, come confronto e solo come confronto

**Decisione.** Accanto all'euristica ammissibile si misura una variante con `V`
pari al 99,9-esimo percentile delle velocita' - 82,0 km/h a Torino e 55,2 a Roma
- dichiarata **non ammissibile** ovunque compaia: nel codice, in una colonna del
CSV dei risultati e nella didascalia della figura.

**Alternative considerate.** Non misurarla affatto; oppure adottarla come
predefinita, guadagnando velocita'.

**Motivo.** Adottarla farebbe perdere la garanzia di ottimalita', che e' una
proprieta' dimostrabile e un punto di forza del progetto. Non misurarla
lascerebbe pero' senza risposta la domanda naturale: quanto costa davvero
rinunciare a quella garanzia? Misurandola si trasforma il difetto dei dati in un
risultato quantificato.

La scelta del 99,9-esimo percentile non e' arbitraria: produce valori fisicamente
plausibili per un mezzo urbano, mentre un percentile piu' basso escluderebbe
tratte veloci legittime, per esempio quelle ferroviarie o metropolitane.

Il numero che conta non e' il risparmio di nodi ma **su quante interrogazioni la
variante restituisce un orario di arrivo diverso dall'ottimo**: e' quello a
misurare il costo reale della rinuncia, invece di lasciarlo come rischio teorico.

**Come si potrebbe verificare.** La colonna `ottimo` di
`results/ricerca_astar.csv` confronta l'orario di ogni variante con quello di
Dijkstra, che non usa euristiche e non puo' quindi essere influenzato da una
stima sbagliata.

---

### 48. L'interfaccia del modello dei ritardi viene fissata prima dei dati

**Decisione.** `src/delays/interfaccia.py` definisce il contratto - una tratta
entra, una distribuzione esce - piu' una implementazione sintetica per lo
sviluppo. Il contratto e' fissato in Fase 2, due settimane prima che i dati
siano disponibili.

**Alternative considerate.** Aspettare i dati e progettare l'interfaccia sulla
forma che il modello appreso assumera'.

**Motivo.** La Fase 4 dovra' comporre distribuzioni di ritardo lungo una catena
di coincidenze. Aspettare i dati per decidere che forma abbia una distribuzione
significherebbe riscrivere le Fasi 2 e 4 quando arrivano. Le quattro operazioni
richieste - funzione di ripartizione, quantile, campionamento e media - non sono
arbitrarie: sono esattamente quelle che le fasi successive usano, la prima per
P(arrivo <= T), la seconda per la pinball loss, la terza per il Monte Carlo, la
quarta per i confronti con le baseline deterministiche.

**Il presidio contro l'uso accidentale.** Un modello sintetico e' per costruzione
indistinguibile da uno vero attraverso l'interfaccia, ed e' proprio questo a
renderlo pericoloso: senza un controllo esplicito basterebbe una dimenticanza per
pubblicare nel documento numeri calcolati su ritardi inventati, e nulla
nell'output lo segnalerebbe. Il presidio ha tre livelli: ogni modello espone un
attributo `sintetico`; ogni script che scriva in `results/` chiama
`assicura_utilizzabile`, che solleva un errore a meno che non sia stato passato
`--sintetico-ammesso`; e ogni CSV porta il nome del modello che lo ha prodotto,
cosi' l'origine di un risultato resta leggibile anche a distanza di mesi.

**Come si potrebbe verificare.** Tentare di eseguire uno script sperimentale con
il modello sintetico senza il permesso esplicito deve fallire con un messaggio che
spiega perche'. Nessun file in `results/` deve riportare `sintetico` nella colonna
del modello.

---

## Fase 4 — Pianificazione robusta

### 49. Una coincidenza persa e' un ritardo, non un fallimento

**Decisione.** Quando la catena perde una coincidenza, il calcolo prosegue sulla
corsa successiva della stessa linea dalla stessa fermata, fino a un tetto di due
recuperi. Solo esaurito il tetto l'itinerario fallisce.

**Alternative considerate.** Il fallimento secco: perdere una coincidenza azzera
la probabilita' di arrivo.

**Motivo.** Il fallimento secco e' molto piu' semplice da calcolare, ma rende
P(arrivo <= T) sistematicamente pessimistica e, soprattutto, **cancella il
fenomeno che la domanda di ricerca vuole misurare**. Un itinerario e' robusto
anche perche', quando perde una coincidenza, ne trova un'altra presto: e' una
proprieta' della rete, non dell'itinerario preso singolarmente, e senza il
recupero due itinerari con la stessa coincidenza tesa ma frequenze molto diverse
risulterebbero identici.

**Il tetto va dichiarato e misurato.** Sulle 1.920 valutazioni della griglia, la
quota media di massa di probabilita' che esaurisce i recuperi e' **9,2%**: il
tetto interviene in circa un caso su undici, abbastanza da meritare una menzione
nel documento ma non tanto da governare i risultati. Sopra il 25% andrebbe
alzato.

**Come si potrebbe verificare.** Il test
`test_una_coincidenza_persa_non_annulla_l_itinerario` costruisce una coincidenza
impossibile da prendere e verifica che la probabilita' resti alta con una
scadenza generosa, e che crolli disattivando i recuperi.

---

### 50. Due metodi di calcolo, e il Monte Carlo vince

**Decisione.** Si implementano sia la convoluzione numerica su griglia temporale
(passo di 10 secondi su quattro ore) sia il campionamento Monte Carlo, e li si
confronta.

**Motivo del confronto.** Servono due implementazioni indipendenti della stessa
quantita' perche' nessuna delle due ha un valore di riferimento esterno: sulla
catena a piu' coincidenze non esiste forma chiusa. La loro concordanza e' l'unica
verifica non circolare disponibile, e la loro divergenza sarebbe il segnale che
una delle due sbaglia.

**Il risultato, che non era quello atteso.** Ci si attendeva che la convoluzione
fosse il metodo esatto e il Monte Carlo l'approssimazione economica. La misura
dice il contrario:

| Metodo | Parametro | Errore | Costo |
| --- | ---: | ---: | ---: |
| convoluzione | passo 5 s | 0,0039 | 96 ms |
| convoluzione | passo 10 s | 0,0049 | 89 ms |
| Monte Carlo | 10.000 campioni | 0,0026 | 25 ms |
| Monte Carlo | 100.000 campioni | 0,0011 | 151 ms |

Il Monte Carlo con diecimila campioni e' **piu' accurato e quasi quattro volte
piu' rapido** della convoluzione con passo di dieci secondi. La ragione e' che il
costo della convoluzione non e' dominato dalla griglia temporale ma dal numero di
interrogazioni al modello dei ritardi, una per bin di ritardo alla salita e per
corsa candidata: raffinare la griglia temporale costa quasi nulla, ma il costo di
base e' gia' superiore a quello del campionamento.

**Perche' la convoluzione resta.** Restituisce un valore **deterministico**: due
esecuzioni danno lo stesso numero, mentre il Monte Carlo ha rumore campionario.
Per il pianificatore, che confronta candidati fra loro, il rumore potrebbe
invertire l'ordine di due itinerari quasi equivalenti. La convoluzione e' percio'
il metodo usato dal pianificatore, e il Monte Carlo quello usato per verificarla.

**Come si potrebbe verificare.** `results/conv_vs_montecarlo.csv` e il test
`test_i_due_metodi_concordano`.

---

### 51. La correlazione lungo la corsa e' un parametro, non una costante

**Decisione.** `ModelloSintetico` accetta un parametro `correlazione` in [0, 1]
che governa quanto il ritardo osservato a monte si trasferisce alla fermata di
discesa. Il valore usato negli esperimenti e' 0,7.

**Alternative considerate.** Cablare una correlazione fissa, o ignorare del tutto
il campo `ritardo_a_monte`.

**Motivo.** Ignorarlo renderebbe la catena artificialmente ottimistica, perche'
tratterebbe come indipendenti il ritardo alla salita e quello alla discesa dello
**stesso mezzo**, che indipendenti non sono. Cablare un valore significherebbe
scrivere il resto del progetto attorno a un numero inventato: in Fase 3 il
modello appreso avra' la correlazione che i dati mostrano, che potrebbe essere
molto diversa.

E' inoltre la leva con cui si controlla quanto due itinerari si distinguano fra
loro, ed era il primo parametro da muovere se il pianificatore robusto e la
baseline piu' veloce fossero coincisi sempre. Non e' stato necessario.

**Come si potrebbe verificare.** A correlazione nulla il condizionamento non ha
effetto e P(arrivo <= T) di una singola tappa coincide con la ripartizione del
ritardo; e' esattamente l'ancoraggio usato dal test
`test_una_sola_tappa_coincide_con_la_forma_chiusa`.

---

### 52. L'insieme candidato e' la frontiera di Pareto, e la misura che lo giustifica

**Decisione.** Il pianificatore massimizza P(arrivo <= T) sulle soluzioni non
dominate della Fase 2, non su tutti gli itinerari possibili.

**Alternative considerate.** Generare, per ogni soluzione della frontiera, le
varianti che partono con la corsa precedente o successiva sulla stessa linea,
allargando l'insieme nella dimensione dei margini.

**Motivo, e il dubbio che lo precedeva.** La frontiera e' calcolata su criteri
deterministici - orario di arrivo, cambi, minuti a piedi - e **collassa gli
itinerari che differiscono solo per il margine sulle coincidenze**, che e'
precisamente la dimensione da cui dipende la robustezza. Massimizzare su un
insieme privo delle alternative rilevanti non sarebbe un limite da dichiarare:
sarebbe un esperimento incapace di rispondere alla domanda.

Il dubbio e' stato risolto misurando, prima di costruire il pianificatore, quanto
P vari lungo la frontiera. La risposta e' che varia molto: mediamente **0,44** di
ampiezza fra la soluzione migliore e la peggiore, e solo **1 coppia su 14** sotto
0,05. La frontiera e' quindi abbastanza ricca, e l'allargamento non e' stato
implementato.

**Una distinzione metodologica che vale la pena riportare.** La prima versione
della misura dava un'ampiezza di **0,66**, ed era **viziata**: includeva
itinerari il cui arrivo *programmato* cadeva gia' dopo la scadenza, che hanno
probabilita' prossima a zero per costruzione. Quella misura non rispondeva alla
domanda posta, perche' registrava soprattutto che un itinerario piu' lento arriva
piu' tardi - il che non e' una scoperta - invece di quanto due itinerari
ugualmente plausibili si distinguano in affidabilita'. Restringendo agli
itinerari **nominalmente fattibili** il valore scende a 0,44, ed e' quello il
numero che risponde. Vale la pena registrarli entrambi: la differenza fra 0,66 e
0,44 e' esattamente la velocita' travestita da robustezza.

**Come si potrebbe verificare.** La colonna `ampiezza_frontiera` di
`results/robusto_griglia_T.csv`, calcolata sui soli candidati nominalmente
fattibili.

---

### 53. La scadenza e' relativa all'itinerario piu' veloce

**Decisione.** T = orario di arrivo dell'itinerario piu' veloce + un margine, e
il margine varia su una griglia di 0, 5, 10, 15, 20 e 30 minuti.

**Alternative considerate.** Una scadenza assoluta, per esempio l'orario di un
appuntamento.

**Motivo.** La domanda di ricerca parla di confronto "a parita' di tempo di
viaggio nominale", e una scadenza ancorata all'itinerario piu' veloce e'
esattamente questo. Una scadenza assoluta introdurrebbe una scelta arbitraria
sull'appuntamento, e i risultati dipenderebbero da quella invece che dal metodo.

Va riconosciuto che questa definizione **e' severa verso il criterio
probabilistico**: ogni itinerario piu' lento di Delta sull'orario deve recuperare
Delta prima ancora di competere, quindi il piu' veloce parte avvantaggiato per
costruzione. E' aritmetica della definizione, non una proprieta' del modello, ed
e' la ragione per cui il vantaggio misurato va letto come un minimo e non come
una stima centrata.

La griglia e' preferita a un singolo valore perche' **le tre grandezze in
funzione del margine sono la dimostrazione di non riducibilita'**: mostrano che
l'ordinamento fra itinerari dipende da T su un campione di ottanta coppie, non su
un esempio scelto ad arte.

**Come si potrebbe verificare.** Se la coincidenza fra pianificatore robusto e
baseline piu' veloce fosse rimasta vicina al 100% su tutta la griglia, la
definizione di T sarebbe stata troppo severa e l'insieme candidato andava
ristretto agli itinerari entro una tolleranza dal piu' veloce. La coincidenza
misurata va dall'88% a margine nullo al 55% a trenta minuti, quindi la
restrizione non e' stata necessaria.

---

### 54. Un test che falliva a intermittenza non e' stato archiviato

**Decisione.** Il modello sintetico deriva i parametri di ogni linea da
`hashlib.blake2b` e non dalla funzione `hash` incorporata.

**Motivo, e il modo in cui e' emerso.** Un test deterministico ha cominciato a
fallire in circa due esecuzioni su tre della suite completa, passando sempre
quando eseguito da solo. La tentazione naturale, di fronte a un test che "a volte
fallisce", e' allargarne la tolleranza o dichiararlo instabile.

La causa era invece un difetto vero: `ModelloSintetico` usava
`hash((seme, route_id))` per derivare i parametri della distribuzione, e **Python
randomizza l'hash delle stringhe a ogni processo**. Lo stesso identificativo di
linea produceva parametri diversi a ogni esecuzione. Il modello si dichiarava
deterministico dato un seme e non lo era, e la verifica che avevo fatto - due
chiamate nello stesso processo - era proprio quella incapace di rivelarlo.

Le conseguenze sarebbero andate ben oltre il test: **ogni esperimento della Fase
4 sarebbe stato irriproducibile**, e il difetto si sarebbe manifestato solo come
numeri che cambiano fra un'esecuzione e l'altra senza alcuna spiegazione, in un
documento che dichiara la riproducibilita' fra i propri requisiti.

E' una voce che dice qualcosa sul metodo prima che sul codice: un test
deterministico che fallisce a intermittenza **non e' un test instabile, e' un
programma non deterministico**, e la differenza fra le due letture e' la
differenza fra trovare il difetto e nasconderlo.

**Come si potrebbe verificare.** Eseguire tre processi separati e confrontare la
media della distribuzione per la stessa tratta: deve essere identica alla sesta
cifra. Prima della correzione non lo era.

---

### 55. Il tratto a piedi finale entra nel tempo di viaggio

**Decisione.** L'itinerario porta un campo `coda_a_piedi` con i secondi di
cammino dopo l'ultima discesa, e tutti i calcoli di probabilita' ne tengono
conto.

**Motivo.** La prima versione del convertitore costruiva le tappe dai soli tratti
percorsi a bordo, quindi calcolava la probabilita' di arrivare **alla fermata di
discesa** invece che a destinazione. Sul campione di Torino il **54% dei
candidati termina con un tratto a piedi**: per piu' della meta' degli itinerari
il tempo di viaggio era sottostimato, e sistematicamente a favore proprio di
quelli che camminano di piu'. Il confronto fra strategie ne sarebbe uscito
falsato nella direzione peggiore, perche' la strategia del margine fisso tende a
scegliere itinerari con piu' cammino.

Il tratto a piedi resta separato dalle tappe perche' non e' soggetto a ritardi:
si cammina sempre alla stessa velocita', e trattarlo come una tappa gli
attribuirebbe una varianza che non ha.

**Come si potrebbe verificare.** Dopo la correzione, l'orario di arrivo
ricostruito dall'itinerario coincide esattamente con quello dell'etichetta di
Pareto su tutti i 106 candidati esaminati. Prima della correzione i due valori
divergevano su tutti gli itinerari con coda a piedi.

---

## Diagnosi del consolidamento

### 56. L'ottimismo delle previsioni lontane: ipotesi formulata e smentita dai dati

**L'ipotesi.** I parquet mostravano una mediana del ritardo negativa su entrambe
le citta', circa -110 s a Roma e -124 s a Torino, cioe' la maggioranza dei mezzi
in anticipo: non plausibile. La spiegazione proposta era che non stessimo
misurando ritardi ma **previsioni**: uno `stop_time_update` per una fermata non
ancora raggiunta e' la stima dell'azienda, e le stime per fermate lontane
sarebbero ottimiste. Ne seguiva che il consolidamento andasse filtrato tenendo,
per ogni passaggio, il solo aggiornamento emesso al momento del passaggio.

**Perche' sembrava vera.** Su Roma la mediana per ora programmata scendeva in
modo netto e ordinato: **-51 s all'ora 13, -264 all'ora 14, -530 all'ora 15**. Le
fermate piu' lontane nel futuro avevano ritardi via via piu' negativi, che e'
esattamente la firma attesa dall'ipotesi. L'andamento sembrava conclusivo.

**Perche' era sbagliata.** La misura veniva da una finestra di raccolta di
**cinquanta minuti**, dalle 13:23 alle 14:13 del primo giorno. In una finestra
cosi' stretta l'ora programmata e l'anticipo della previsione **non sono due
variabili ma una sola travestita**: una fermata programmata alle 15 e' per forza
osservata con almeno tre quarti d'ora di anticipo, e una programmata alle 13 e'
per forza gia' passata. L'andamento orario non poteva quindi dire nulla
sull'anticipo, e leggerlo come se lo dicesse era una correlazione spuria per
costruzione.

Separando le due variabili, l'effetto sparisce. La mediana del ritardo per fascia
di anticipo, su Roma, e' -190 s per le fermate gia' passate, -138 fra zero e
cinque minuti, -108 fra cinque e quindici, -120 fra quindici e trenta e -192 fra
trenta e sessanta: **nessuna tendenza**. Se le previsioni lontane fossero
ottimiste quella colonna crescerebbe in modo monotono. Controllando anche per
l'ora programmata il quadro si conferma, e dentro l'ora 13 la mediana passa
addirittura da -157 a +217 al crescere dell'anticipo, cioe' nella direzione
opposta.

Il filtro proposto e' stato comunque misurato: non risolve. Su Roma sposta la
mediana da -134 a -164 s, quindi la peggiora; su Torino da -166 a -129, e in
nessuna delle due appiattisce l'andamento orario.

**Che cosa resta.** Tutte le spiegazioni meccaniche sono state escluse: la
conversione degli orari oltre le 24 ore e' corretta, la giunzione con l'orario
statico pure - su Roma la nostra ricostruzione coincide con il `delay` dichiarato
dall'azienda con scarto mediano nullo e concordanza entro 60 s sul 99,6% degli
eventi - il `delay` esplicito e' gia' preferito dove esiste, e arrivo e partenza
nell'orario statico coincidono sul 100% delle fermate, quindi non c'e' sosta che
possa spiegare uno scarto. Resta come spiegazione piu' plausibile che la mediana
negativa sia **cio' che le aziende dichiarano**, verosimilmente per il margine
inserito negli orari pubblicati. Non e' pero' ancora una conclusione: poggia su
una giornata parziale, e va verificata sui giorni pieni prima di entrare nel
documento.

**Che cosa il filtro ha comunque prodotto.** Due misure che restano valide
indipendentemente dall'ipotesi. La prima e' che le previsioni sono emesse con
anticipi molto diversi nelle due citta': mediana **15,8 minuti su Roma** contro
**2,1 su Torino**, con terzo quartile 27,4 contro 4,4. Le due colonne
`ritardo_secondi` non sono la stessa grandezza, e la Fase 3 deve trattarle
diversamente. La seconda e' il dimensionamento: filtrando al momento del
passaggio sopravvive il 3,9% delle righe su Roma e circa il 10% su Torino, cioe'
dell'ordine di 330 mila e 145 mila righe al giorno, abbondanti per
l'apprendimento.

**Come si potrebbe verificare.** `scripts/diagnosi_consolidamento.py` rifa
l'intera diagnosi su una giornata piena, con il quadro dell'anticipo calcolato
**dentro** ciascuna fascia oraria, che e' l'unico modo di separare le due
variabili. Se su giornate intere la mediana risultasse negativa a tutte le ore,
comprese la notte e le ore di morbida, l'ipotesi del margine negli orari si
rafforzerebbe; se lo fosse solo di giorno, la spiegazione sarebbe un'altra.

**Aggiornamento sui giorni pieni: smentita con il segno contrario.** Le
conclusioni sopra venivano da una giornata parziale ed erano formulate come "non
confermata". Sul 28 agosto, giornata intera, il quadro e' piu' netto e va
registrato come tale. Su Torino la mediana del ritardo per fascia di anticipo,
**identica in ciascuna delle cinque fasce orarie in cui e' replicata** e su basi
fra le ottomila e le venticinquemila righe, e' di **-293 s per le fermate gia'
passate, -144 fra zero e cinque minuti, -63 fra cinque e quindici, +853 fra
quindici e trenta e +1.845 oltre**. Su Roma, dove le basi reggono, l'ora 13 da'
-223, -177, -113, -100.

La mediana diventa dunque **meno** negativa, fino a cambiare segno, quanto piu' la
previsione e' lontana. Non e' assenza dell'effetto atteso: e' l'effetto opposto.
L'ipotesi dell'ottimismo delle previsioni lontane non e' semplicemente non
confermata, e' **smentita**.

**La lezione di metodo.** Un andamento ordinato e monotono su tre punti e' molto
persuasivo, e lo era per entrambi gli autori di questa voce. Ma prima di leggerlo
come causale va chiesto se la finestra di misura permetta alle due variabili di
variare separatamente: qui non lo permetteva, e nessuna quantita' di dati raccolti
in quella finestra avrebbe potuto rivelarlo.

---

### 57. Le corse con ritardo enorme sono spostate in blocco, e non si scartano

**Decisione.** Le righe con ritardo superiore all'ora, una volta separate dai
salti di giorno, restano nel dataset e non vengono filtrate.

**La lettura e' cambiata due volte, e il secondo cambiamento era un errore.** Vale
la pena riportare i tre passaggi nell'ordine in cui sono avvenuti, perche' il
percorso dice piu' della conclusione.

*Sui dati parziali sembravano corse spostate in blocco.* Sedici corse di una
giornata incompleta, con il 77% delle righe anomalo e una deviazione standard
interna di 223 s contro una media di 5.017: il ritardo era pressoche' costante
lungo tutto il percorso.

*Sui dati completi sembravano il contrario.* Su due giornate intere la quota di
righe anomale dentro le corse colpite scendeva al 25%, e le corse erano 532 e 536.
Se ne era concluso che non fossero corse traslate ma corse con alcune fermate
anomale e altre normali, e che il campione parziale avesse suggerito una struttura
inesistente.

*Sui dati completi e correttamente classificati sono di nuovo corse spostate in
blocco.* Quella seconda lettura era viziata: il criterio che separava i salti di
giorno dal resto riconosceva come tali solo le righe entro dieci minuti da 86.400
s, e lasciava quindi **33.683 righe di rollover** dentro la popolazione da
descrivere, abbassandone la quota di anomalie. Con il criterio del residuo il
quadro si rovescia.

| | 27 ago | 28 ago |
| --- | ---: | ---: |
| Corse esaminate | 274 | 257 |
| Quota di fermate anomale dentro la corsa | 78,4% | 96,7% |
| Con un solo tratto anomalo contiguo | 94,5% | 93,8% |
| Tratti separati per corsa (mediana / massimo) | 1 / 3 | 1 / 4 |
| Posizione del primo tratto (0 = inizio) | 0,02 | 0,00 |
| Ritardo, fermate anomale contro normali | 4.738 / 27 s | 4.419 / 32 s |

Le misure convergono su una sola descrizione. Le fermate anomale sono
**contigue** nel 94% delle corse, e formano un solo tratto: nessun difetto di
trasmissione produce un blocco unico, mentre un evento fisico e' per forza
localizzato. Il tratto comincia **all'inizio del percorso**, con mediana 0,00 e
0,02, quindi la corsa parte gia' in ritardo invece di accumularlo strada facendo.
E lo scarto con le fermate normali della **stessa** corsa e' un gradino, non una
degradazione.

**Il dettaglio che chiude la questione.** Le fermate normali di quelle corse hanno
mediana **+27 e +32 secondi**, cioe' praticamente in orario, contro i -394 e -438
misurati sulla popolazione contaminata. Sono corse che partono con un'ora
abbondante di ritardo e poi **rientrano quasi esattamente in orario**. E' il
profilo di un recupero, ed e' incompatibile sia con una degradazione progressiva
sia con un difetto di misura, che non avrebbe ragione di sanarsi a meta' percorso.

**I ritardi si addensano su una fascia, non su un valore.** La concentrazione sul
valore piu' frequente e' del 12,3% e 12,8%, che non e' un picco: i primi cinque
valori stanno tutti fra i 60 e gli 80 minuti e insieme fanno il 48% e il 59%. Non
c'e' dunque il valore ricorrente che tradirebbe un'etichetta sbagliata, ma un
addensamento attorno all'ora abbondante.

**L'ipotesi alternativa e' stata verificata ed e' esclusa.** Se quell'ora
corrispondesse all'intervallo fra due corse successive della stessa linea, la
spiegazione naturale sarebbe che il feed descrive il veicolo successivo sotto
l'identificativo del precedente. Misurato sull'orario statico di Roma, fra le 6 e
le 21, l'intervallo mediano fra corse successive e' di **2 minuti**, sale a 5 al
novantesimo percentile, e su 387 linee **nessuna** supera i 60 minuti di mediana.
Le nove linee coinvolte nel campione locale hanno intervalli fra 0 e 4 minuti. Un
addensamento fra 60 e 80 minuti e' quindi da quindici a quaranta volte
l'intervallo tipico, e l'ipotesi non regge.

Resta un'alternativa che questi dati non permettono di escludere: un'ora
abbondante e' dell'ordine del tempo di **giro completo** di una linea urbana,
quindi un veicolo in ritardo di un intero ciclo produrrebbe lo stesso profilo. Dal
punto di vista di chi aspetta alla fermata le due cose coincidono - il mezzo
arriva un'ora dopo - e la distinzione richiederebbe il ``block_id``, che su Roma
non e' valorizzato. Si dichiara indecidibile.

**Perche' non si scartano.** Sono osservazioni valide, e per l'apprendimento del
modello dei ritardi sono **le piu' informative che abbiamo**: descrivono la coda
della distribuzione, cioe' esattamente la situazione in cui un pianificatore
robusto ha una ragione di esistere. Un modello addestrato senza di esse
imparerebbe un mondo in cui il ritardo grave non accade, e assegnerebbe a ogni
itinerario una probabilita' di arrivo sistematicamente ottimistica proprio nei
casi che il progetto vuole distinguere.

**Il punto di metodo, che non e' quello che sembrava.** La lettura intermedia
sbagliata non veniva da un campione troppo piccolo: veniva da **dati completi
classificati male**. Il campione parziale, con sedici corse su una giornata
monca, aveva dato la risposta giusta; le due giornate intere, con la popolazione
inquinata da trentatremila righe di rollover, l'avevano data sbagliata.

La morale non e' dunque "servono piu' dati" ma **"i dati vanno separati prima di
essere descritti"**. Una descrizione statistica e' valida solo quanto la
definizione della popolazione su cui e' calcolata, e un criterio di
classificazione approssimativo non produce rumore: produce una struttura
apparente, ordinata e persuasiva quanto quella vera. Qui il criterio sbagliato non
ha reso i numeri incerti, li ha resi coerenti con una conclusione falsa.

**Come si potrebbe verificare.** Il quadro 1-quinquies di
`scripts/diagnosi_consolidamento.py` calcola le cinque grandezze della tabella, ed
e' collaudato su venti corse a struttura nota, dieci con tratto contiguo e dieci
con fermate sparse, di cui ritrova esattamente la composizione. Il quadro 1
riporta quante righe sfuggirebbero al criterio stretto: sul 28 agosto sono 33.683.
La misura sugli intervalli fra corse e' rifacibile dal solo orario statico.

### 58. La chiave di deduplica: difetto reale, effetto nullo, e una misura scelta male

**Decisione.** La chiave della deduplica include la data di servizio. La
correzione si tiene, ma il suo effetto misurato e' **nullo**, e questa voce esiste
per la seconda meta' di quella frase piu' che per la prima.

**La collisione esisteva davvero.** Attorno alla mezzanotte una cartella contiene
due giorni di servizio, perche' le corse notturne del giorno precedente sono
ancora in circolazione e riportano la propria `start_date`. Con una chiave fatta
di sola corsa e posizione, due passaggi distinti condividono lo stesso posto nello
stato della deduplica. Sul 28 agosto le coppie coinvolte su Roma erano **9.606**.
Non e' un fenomeno immaginato.

**L'effetto sulle righe era nullo.** Misurato dopo la correzione, su una giornata
intera:

| | righe conservate che la chiave storica avrebbe scartato | righe scartate che avrebbe scritto in piu' | su un totale di |
| --- | ---: | ---: | ---: |
| Roma | 4 | 0 | 9.569.851 |
| Torino | 0 | 0 | 1.516.786 |

Quattro righe su nove milioni e mezzo. La ragione e' nel meccanismo: la deduplica
scarta una riga solo quando il valore osservato **coincide** con il precedente, e
due passaggi a ventiquattro ore di distanza hanno orari che differiscono di 86.400
secondi. La soppressione a torto richiede una coincidenza che non si verifica.

**Il numero che avevo usato come prova non misurava cio' che credevo.** Le 9.606
coppie erano state tradotte in "quasi 194.000 righe coinvolte, il 2% del file", e
quel 2% era stato annunciato come il piu' grosso dei tre difetti trovati dalla
diagnosi. Ma **righe appartenenti a coppie in collisione** e **righe perse** sono
grandezze diverse: la prima conta tutte le osservazioni di ogni coppia che
compaia in due giorni, la seconda solo quelle che la deduplica ha effettivamente
scartato a torto. Averle scambiate ha fatto sembrare dominante un difetto
marginale, e ha determinato l'ordine di lavoro delle correzioni successive.

C'e' anche una direzione opposta che era sfuggita del tutto. Alternando fra i due
giorni di servizio, la chiave senza data vede un valore diverso a ogni giro e
registra un cambio che non c'e': scrive righe **in piu'**, non in meno. Le due
direzioni si compensano.

**Perche' la correzione si tiene comunque.** Una chiave che non distingue due
passaggi distinti e' sbagliata a prescindere da quanto costi oggi. Il costo
dipende da una circostanza contingente - che gli orari osservati dei due giorni
non coincidano quasi mai - e non da una proprieta' del modello: basterebbe un feed
che riporti l'orario in forma relativa, o una politica di deduplica diversa,
perche' lo stesso difetto diventasse grave. Si corregge cio' che e' sbagliato, non
cio' che al momento fa danno.

**Il punto di metodo, che e' la ragione di questa voce.** La misura con cui si
verifica una correzione va scelta **prima** di correggere. Scegliendola dopo si
sceglie, senza accorgersene, quella che conferma cio' che si crede gia'.

Qui la misura usata come prova e' stata il conteggio totale delle righe del
parquet, prima e dopo. Quel numero non poteva dire nulla, e non per sfortuna ma
per costruzione: le due direzioni dell'errore si compensano, quindi il totale
resta fermo sia se la correzione non fa nulla sia se fa molto in entrambi i versi.
E' un numero che non distingue le ipotesi che dovrebbe distinguere.

La misura giusta esisteva ed era semplice: contare, durante il consolidamento,
quante righe la chiave storica avrebbe scartato e quante ne avrebbe scritte in
piu', tenendo uno stato ombra che non influenza cio' che viene scritto. Costa un
dizionario e due contatori, e li riporta il riepilogo di `consolida_giorno`. Se
fosse stata scritta prima della correzione, avrebbe detto subito che il difetto
valeva quattro righe, e le priorita' sarebbero state altre.

**Lo stesso errore e' ricomparso due giorni dopo, il che rende questo punto meno
teorico di come suona.** I due contatori appena descritti restavano a **zero**
sotto la politica di deduplica `ultimo`, perche' quel ramo esce prima di
aggiornare lo stato ombra. Uno zero che significa "non misurato" sarebbe stato
letto come "nessun effetto": esattamente la confusione fra due grandezze diverse
che questa voce documenta, ricomparsa nello stesso codice scritto per porvi
rimedio. E il caso era per giunta quello in cui il difetto della chiave e' piu'
grave, perche' sotto `ultimo` si conserva una riga per chiave e la chiave senza
data ne terrebbe una sola per due giorni di servizio, perdendo un passaggio
intero invece di una ripetizione.

La lezione da trarne non e' che serva piu' attenzione, ma che **un contatore deve
distinguere lo zero misurato dallo zero non misurato**, perche' chi lo legge non
puo' vedere la differenza. Dove i due casi esistono, o si misura anche il secondo
o lo si dichiara.

**Come si potrebbe verificare.** I due contatori del riepilogo, su qualunque
giorno. I test `test_si_misura_l_effetto_della_data_nella_chiave`,
`test_la_soppressione_a_torto_si_conta_nell_altra_direzione` e
`test_sotto_la_politica_ultimo_la_data_nella_chiave_salva_un_passaggio`
costruiscono i casi separatamente e verificano che ciascun contatore risponda al
proprio e non all'altro, sotto entrambe le politiche.

---

### 59. Due filosofie di pubblicazione, misurate su quattro grandezze indipendenti

**Decisione.** La differenza fra i due produttori di dati viene registrata come
fatto misurato e non come impressione, e vincola la Fase 3: le colonne
`ritardo_secondi` delle due citta' non entrano nello stesso modello senza che la
differenza sia dichiarata e trattata.

**Alternative considerate.** Trattare Roma e Torino come due repliche dello stesso
fenomeno, con un modello unico e la citta' come semplice variabile esplicativa.

**Il dato che ha chiuso il quadro: i payload corrotti.** Contati sul journal fra
il 27 agosto e il 5 settembre, undici giorni:

| | payload protobuf corrotti |
| --- | ---: |
| Roma, `trip_updates` | 42 |
| Roma, `vehicle_positions` | 52 |
| Torino, entrambi i feed | 0 |

Sui `trip_updates`, che sono la fonte del progetto, sono **42 su circa 32.000
interrogazioni, cioe' lo 0,13%**: trascurabile per i risultati. Il collector li
rileva, li scarta e prosegue, che e' il comportamento voluto e gia' documentato
alla voce 11; se li accettasse, il parquet conterrebbe righe interpretate da byte
casuali senza che nulla lo segnali.

**Le quattro misure, e perche' contano insieme.**

| grandezza | Roma | Torino |
| --- | ---: | ---: |
| Anticipo mediano delle previsioni | 15,8 min | 2,1 min |
| Righe con ritardo oltre l'ora (28 agosto) | 100.856 | 27 |
| Revisioni dell'orario in quindici giorni | 15 su 15 | 5 su 15 |
| Payload corrotti in undici giorni | 94 | 0 |
| Osservazioni conservate per passaggio, a cadenza pari | 20,3 | 7,1 |
| Fin dove nel passato arriva il feed | 70.229 s | **4 s** |

La quinta riga e' arrivata dopo le altre, con la rigenerazione completa, e le
conferma dall'interno. Va pero' letta **a cadenza pari**, perche' quel numero
dipende da quanto spesso si interroga almeno quanto da chi pubblica (voce 76):
sulle sole giornate a cadenza piena sono 20,3 osservazioni per passaggio su Roma
e 7,1 su Torino, un divario di 2,87 volte. La versione precedente, 17,0 contro
7,0, mescolava le giornate romane a cadenza ridotta e **sottostimava** la
differenza. Chi emette previsioni con quindici minuti
di anticipo ha il tempo di correggersi molte volte prima del passaggio; chi le
emette con due non ce l'ha. Non e' una misura indipendente dalle altre ma la loro
conseguenza aritmetica, ed e' per questo che vale: se fosse risultata uguale nelle
due citta', una delle altre quattro sarebbe stata da rivedere.

**La sesta riga e' arrivata per ultima ed e' la piu' grave**, perche' non misura
la qualita' del dato ma che cosa il dato sia. E' il massimo, su quattordici
giornate, di `timestamp_feed - orario_programmato`: quanto in la' nel passato il
produttore continua a pubblicare una fermata. Roma arriva a diciannove ore, Torino
a **quattro secondi**. Torino cioe' toglie la fermata dal feed appena il mezzo vi
transita, e nei suoi dati non esiste un solo passaggio osservato dopo che e'
avvenuto. Le altre cinque righe dicono che i due produttori pubblicano lo stesso
genere di cosa con cura diversa; la sesta dice che uno dei due non pubblica affatto
il genere di cosa che l'altro pubblica. Le conseguenze sono nella voce 63.

Prese una alla volta sarebbero anomalie separate, ciascuna con la propria
spiegazione locale. Prese insieme descrivono **due modi diversi di intendere la
pubblicazione di dati aperti**, e la coerenza fra misure indipendenti e' cio' che
trasforma un'impressione in un'osservazione. Roma pubblica molto, lontano nel
tempo e con qualita' variabile: previsioni emesse con un quarto d'ora di anticipo,
orario che cambia **ogni giorno senza eccezioni**, una frazione piccola ma non
nulla di trasmissioni malformate. Torino pubblica poco, vicino e pulito:
previsioni a due minuti dal passaggio, orario che cambia una volta ogni tre
giorni, nessun payload corrotto in undici giorni.

**Motivo per cui questo vincola la Fase 3.** Le due colonne `ritardo_secondi` non
descrivono la stessa grandezza con la stessa affidabilita'. Su Roma il valore e'
in larga parte una previsione emessa con quindici minuti di anticipo; su Torino
e' quasi una constatazione. Un modello unico che le tratti come repliche
imparerebbe una distribuzione mediata fra due processi diversi, e la citta' come
variabile esplicativa non basterebbe a separarli, perche' la differenza non e' di
livello ma di **natura della misura**. Si stimeranno percio' distribuzioni
separate per citta', e il confronto fra le due sara' esso stesso un risultato da
riportare invece che un fastidio da assorbire.

Va aggiunto che questa differenza si somma a quella gia' registrata sulla
copertura: su Roma il tempo reale non comprende la metropolitana, quindi il
modello romano sara' un modello dei ritardi degli autobus. Le due citta'
differiscono dunque per che cosa osservano, con quale anticipo, con quale
stabilita' dell'orario di riferimento, con quale qualita' di trasmissione e - la
piu' profonda - se **osservino affatto** il passaggio o soltanto lo prevedano.

**Una conseguenza sulla Fase 5, da dichiarare ora.** Su Torino il backtesting non
potra' verificare gli itinerari contro i ritardi realmente avvenuti, perche' quei
numeri non esistono nel dato: li verifichera' contro l'ultima stima del produttore
prima che la fermata sparisca dal feed, emessa con una mediana di circa due minuti
di anticipo. E' una limitazione della **misura**, non del metodo, e va scritta
accanto ai risultati torinesi invece che lasciata implicita. Su Roma non si
applica, perche' li' il feed continua a pubblicare la fermata per una mezz'ora
buona dopo il passaggio e le constatazioni ci sono davvero.

**Come si potrebbe verificare.** I payload corrotti si contano nel journal del
servizio, cercando le righe di scarto emesse dal collector. L'anticipo delle
previsioni e' il quadro 4 di `scripts/diagnosi_consolidamento.py`, le righe con
ritardo oltre l'ora il quadro 1, e le revisioni dell'orario si leggono dalla
sezione `versioni` di `data/raw/gtfs/<citta>/index.json`. La sesta riga e' la
colonna `feed_meno_programmato_max` di `scripts/diagnosi_constatazioni.py`. In Fase 3, la verifica
decisiva sara' un'altra: stimare il modello su una citta' e valutarlo sull'altra.
Se la differenza fosse di solo livello, la perdita sarebbe modesta; se e' di
natura, il modello trasferito sara' mal calibrato, e la misura di quanto lo sia
e' il modo di quantificare tutto questo con un numero solo.

---

### 60. Condizionare sul bin non e' condizionare sulla variabile

**Decisione.** Il test della proprieta' markoviana non si giudica sul solo
riferimento per permutazione, ma sul **verso con cui l'eccesso varia al raffinarsi
della discretizzazione**.

**Che cosa avremmo concluso con il solo riferimento per permutazione.** Il criterio
approvato nel piano era: si stima `I(R0 ; R-2 | R-1)`, si costruisce lo zero
effettivo rimescolando `R-2` dentro gli strati di `R-1`, e si confronta. E'
corretto per cio' che quel riferimento misura, cioe' il bias di stima su campioni
finiti, ed e' indispensabile: l'informazione mutua stimata da frequenze e' sempre
positiva anche quando la vera e' zero.

Non basta. Su una catena costruita in modo da essere **markoviana in senso esatto**
- `R0 = R-1 + rumore`, quindi `R0` indipendente da `R-2` dato `R-1` per
costruzione - e discretizzata negli otto bin del progetto, la misura da:

| | valore in bit |
| --- | ---: |
| Informazione condizionata | 0,01174 |
| Riferimento per permutazione | 0,00087 ± 0,00007 |
| Eccesso | **0,01086** |

L'eccesso e' **dodici volte** il riferimento. Applicando il criterio approvato,
avremmo dichiarato non markoviano un processo markoviano per costruzione, e
aggiunto alla rete un arco che moltiplica per otto il numero delle celle da
stimare, sulla base di un artefatto.

**Perche' succede.** Perche' **condizionare sul bin non e' condizionare sulla
variabile**. Il bin di `R-1` non porta tutta l'informazione del valore continuo
che rappresenta: dentro lo stesso bin si trovano ritardi diversi, e `R-2`
conserva un residuo di informazione su *dove dentro il bin* fosse `R-1`. Quel
residuo si manifesta come dipendenza condizionata, ed e' reale nella
rappresentazione discretizzata pur non esistendo nel processo.

**Il discriminante: il verso della scala.** L'artefatto ha una firma che una
dipendenza vera non ha, e si dissolve al raffinarsi dei bin, perche' bin piu'
stretti perdono meno informazione. Sulla stessa catena markoviana per costruzione:

| bin | eccesso, in quota su cio' che il primo antenato spiega |
| ---: | ---: |
| 2 | 3,6% |
| 4 | 5,0% |
| 6 | 3,0% |
| 8 | 1,0% |
| 12 | 0,2% |
| 20 | 0,1% |

Una dipendenza vera non ha ragione di svanire, e anzi emerge meglio quando i bin
smettono di confonderla: verificato su una catena in cui `R0` dipende
direttamente anche da `R-2`, dove la quota non si dissolve. Il criterio e' quindi
che **se l'eccesso cala verso zero al crescere dei bin e' discretizzazione, se
resta o cresce e' struttura**. Il suo pregio rispetto a un surrogato simulato e'
che non richiede alcuna ipotesi sul processo continuo sottostante, che sui dati
veri non conosciamo.

**Il punto di metodo.** Questo non e' stato progettato, e' stato **trovato
costruendo il collaudo**. Il criterio della permutazione era stato pensato a
tavolino e sembrava sufficiente a entrambi; il difetto e' emerso perche' il test
dell'estimatore era stato scritto su catene **a struttura nota**, dove la risposta
giusta era decisa in anticipo, e una di quelle catene ha dato la risposta
sbagliata. Un collaudo su dati veri non avrebbe potuto rivelarlo, perche' li' la
risposta non e' nota e un eccesso di 0,011 bit sarebbe sembrato un risultato.

E' la stessa lezione della voce 58 vista da un altro lato. Li' la misura di
verifica era stata scelta dopo la correzione, e confermava cio' che si credeva
gia'. Qui il criterio era stato scelto prima, ma **non era stato messo alla prova
su un caso di cui si conoscesse la risposta**: sceglierla prima non basta, bisogna
anche provare che sappia distinguere i casi che deve distinguere.

**Una conseguenza che va oltre questo test, e che va nel documento.** Se
condizionare sul bin non e' condizionare sulla variabile, allora **ogni
indipendenza condizionata che la struttura della rete assume e' approssimata dalla
discretizzazione, non esatta**. L'arco che non c'e' fra due variabili significa
"indipendenti dato il genitore", ma il genitore che la rete osserva e' un bin, non
un ritardo: una parte di dipendenza sopravvive sempre, tanto maggiore quanto piu'
grossolani sono i bin.

Non e' un difetto da correggere. Discretizzare e' necessario, perche' senza non ci
sarebbero tabelle di probabilita' da stimare, e bin piu' fini che riducono
l'approssimazione moltiplicano le celle e peggiorano la stima: e' un compromesso,
non un errore. Ma e' un **limite del modello da dichiarare**, accanto alla scelta
degli otto bin e non in fondo alle conclusioni, perche' qualifica il significato
di ogni arco assente nel grafo.

**Esito sui dati veri, e perche' la risposta non e' binaria.** Il criterio ha
funzionato, nel senso che ha distinto un caso reale da un artefatto: su 8,4
milioni di terne per Roma e 2,5 per Torino l'eccesso **non si dissolve** in
nessuna delle sei combinazioni di citta' e popolazione, mentre sulla catena
markoviana costruita si dissolveva. Il riferimento per permutazione e' ormai
trascurabile, 0,00003 bit, a conferma che con questa numerosita' il confondente
che misura non e' piu' in gioco.

Quota dell'eccesso su cio' che il primo antenato spiega, per granularita':

| | 4 bin | 6 bin | 8 bin | 12 bin | 20 bin |
| --- | ---: | ---: | ---: | ---: | ---: |
| Roma, tutte | 2,52% | 2,21% | 2,17% | 1,97% | 1,63% |
| Roma, solo previsioni | 1,94% | 1,60% | 1,58% | 1,47% | 1,25% |
| Roma, solo gia' passate | 4,73% | 3,87% | 3,58% | 3,01% | 2,41% |
| Torino, tutte | 2,13% | 5,31% | 2,95% | 3,15% | 2,88% |
| Torino, solo previsioni | 1,51% | 5,69% | 2,13% | 2,43% | 2,42% |
| Torino, solo gia' passate | 2,71% | 2,71% | 3,20% | 3,32% | - |

**Il criterio era binario e i dati hanno prodotto un terzo caso.** Su Roma la
scala non si dissolve secondo la soglia - l'ultimo valore non scende sotto un
terzo del primo - ma **cala in modo regolare e monotono** su tutte e tre le
popolazioni. Non e' ne' la dissoluzione dell'artefatto ne' la persistenza di una
struttura: e' compatibile con la presenza di **entrambe**, dove la parte di
artefatto si dissolve e quella di struttura resta. Se cosi' fosse, il valore alla
granularita' piu' fine e' la stima migliore della dipendenza vera, e i valori a
bin larghi la sovrastimano. Su Torino la scala oscilla invece di calare, e il
5,31% a sei bin e' fuori linea rispetto ai vicini: li' la lettura e' meno
leggibile e va trattata con piu' cautela.

**Il capovolgimento su Roma, che smentisce l'attesa.** Ci si aspettava che, se la
dipendenza fosse un artefatto del produttore, le previsioni risultassero **piu'**
correlate delle constatazioni, perche' previsioni successive della stessa corsa
sono prodotte dallo stesso algoritmo a pochi minuti di distanza. Il dato dice il
contrario, e a ogni granularita': sulle osservazioni **gia' passate** l'eccesso e'
circa il **doppio** che sulle previsioni, 3,58% contro 1,58% a otto bin e 2,41%
contro 1,25% a venti. La dipendenza non viene dunque dal modo in cui il feed e'
prodotto ma dalle osservazioni piu' vicine alla realta'. Resta da escludere una
spiegazione alternativa prima di considerarlo acquisito: le terne gia' passate
sono circa un decimo del totale e potrebbero avere fermate piu' ravvicinate nel
tempo, e fermate vicine condividono piu' informazione a prescindere dalla natura
del dato. Il controllo e' un confronto **a parita' di ampiezza temporale della
terna**, ed e' implementato in `scripts/markov_terne.py`.

**Che cosa ne consegue per la decisione, e il punto di metodo aggiornato.** "Non
si dissolve" **non implica "aggiungi l'arco"**: implica "misura quanto vale". La
dipendenza c'e' ma e' piccola, fra l'1,3% e il 5,6% di quanto il primo antenato
gia' spiega, e un arco in piu' moltiplica per otto le celle da stimare. La
domanda che decide la struttura non e' se la dipendenza esista - la risposta e'
si' - ma se **sopravviva fuori campione** al costo della propria stima, e si
risponde confrontando la perdita logaritmica dei due modelli su giornate non usate
per stimarli. Se il guadagno fosse dell'ordine dell'uno o due per cento, l'arco
non si aggiunge e l'assunzione markoviana si tiene come **approssimazione
dichiarata** e non come verita': e' una differenza che va scritta nel documento,
perche' cambia cio' che il modello promette.

Il punto di metodo si somma a quello gia' registrato sopra. Non basta scegliere la
misura prima di correggere, ne' provarla su casi di risposta nota: bisogna anche
chiedersi **se la domanda ammetta le risposte che il criterio prevede**. Qui il
criterio ne prevedeva due, si dissolve o non si dissolve, e i dati ne hanno
prodotta una terza che non era contemplata.

**Esito finale: due misure dello stesso arco, di segno opposto.** La decisione e'
stata presa confrontando la perdita logaritmica fuori campione con e senza
l'arco. La misura e' stata fatta due volte, e i due risultati si contraddicono
solo in apparenza.

| | senza contesto | dentro il modello con contesto | oss. per cella con l'arco |
| --- | ---: | ---: | ---: |
| Roma, tutte | +3,64% | **-2,89%** | 2,15 |
| Roma, solo previsioni | +3,79% | **-7,49%** | 0,81 |
| Roma, solo gia' passate | +5,02% | **-10,04%** | 0,20 |
| Torino, tutte | +3,47% | **-0,35%** | 2,26 |
| Torino, solo previsioni | +2,37% | **-2,63%** | 0,99 |
| Torino, solo gia' passate | +4,48% | **-1,82%** | 0,36 |

*Numeri della corsa del 12 settembre 2026 sulle sedici giornate della finestra
dichiarata (25 agosto - 9 settembre), da `results/markov_terne.csv`. La prima
stesura di questa voce riportava una corsa su quattordici giornate, i cui numeri
- da +2,37% a +7,67% senza contesto e da -4,04% a -8,58% con contesto - vanno
scartati: erano giusti sulla loro finestra, e la finestra non era dichiarata.*

La prima colonna confronta `P(R0|R-1)` con `P(R0|R-1,R-2)`: sessantaquattro celle
contro cinquecentododici, su 2,07 milioni di terne di verifica per Roma e 648 mila
per Torino. Entrambi i modelli sono stimati in abbondanza, e l'arco guadagna fra il
2 e il 5%. La seconda colonna rifa' lo stesso confronto **dentro il modello vero**,
dove il ritardo e' condizionato anche a linea, fascia oraria e tipo di giorno: li'
le celle passano da 466 mila a 3,7 milioni, e l'arco **peggiora su tutte e sei le
combinazioni**.

La causa e' nella terza colonna: con l'arco le osservazioni per cella in
addestramento stanno fra 2,26 e 0,20, quindi la maggior parte delle celle non riceve
nemmeno un dato, e una tabella stimata su celle vuote e' peggiore di una tabella
piu' grossolana stimata su celle piene.

**Un caso che indebolisce la conclusione, e va detto.** Su Torino e sull'insieme di
tutte le coppie l'arco peggiora dello **0,35%**, cioe' quasi nulla: li' non paga ma
nemmeno costa, e se fosse stato l'unico caso disponibile la decisione sarebbe rimasta
aperta. Con quattordici giornate quella cella valeva -4,04% e l'intervallo faceva
sembrare la conclusione piu' solida di quanto sia. Regge perche' il segno e' lo stesso
su tutte e sei le combinazioni e perche' la causa e' misurata; non perche' il margine
sia ampio ovunque.

**I due numeri non si contraddicono: rispondono a domande diverse.** "Il secondo
antenato porta informazione?" e' una domanda **sui dati**, e la risposta e' si',
misurata e non trascurabile. "L'arco migliora il modello?" e' una domanda **sul
modello**, e la risposta e' no. Confonderle avrebbe fatto aggiungere un arco che
peggiora del 6%, e per giunta sulla base di una misura corretta.

**Decisione: l'arco non si aggiunge, e l'assunzione markoviana si tiene come
approssimazione dichiarata.** La dipendenza esiste, e' misurata, e vale fra l'1,3%
e il 5,6% di cio' che il primo antenato spiega. Non la si rappresenta perche' il
modello non ha i dati per sostenerla. E' una posizione **piu' forte** di quella di
partenza, non piu' debole: la Fase 4 assumeva la markovianita' senza averla
verificata, mentre ora si sa che cosa si sta trascurando e quanto vale.

**Il punto di metodo, che e' la ragione per cui questa voce e' cresciuta tre
volte.** Una misura va fatta **nel regime in cui la decisione si applica**, non in
quello in cui e' piu' comoda da calcolare. Il confronto senza contesto era piu'
semplice da scrivere, piu' rapido da eseguire e piu' facile da leggere, ed era
corretto: misurava esattamente cio' che dichiarava. Era pero' calcolato in
abbondanza di dati, mentre la decisione si applica in scarsita', e fra i due
regimi il segno del risultato cambia. Nessun controllo sulla correttezza della
misura avrebbe potuto rivelarlo, perche' la misura non era sbagliata: era fatta
altrove.

**Come si potrebbe verificare.** I test
`test_discretizzare_una_catena_markoviana_crea_dipendenza_apparente`,
`test_l_artefatto_della_discretizzazione_si_dissolve_al_raffinarsi_dei_bin` e
`test_una_dipendenza_vera_non_si_dissolve` fissano i tre comportamenti su catene
costruite, e `test_il_confronto_con_contesto_penalizza_la_scarsita` fissa il
capovolgimento fra i due regimi. Sui dati veri, la funzione `scala_per_granularita` di
`src/delays/markov.py` produce la tabella della scala per ciascuna citta'.

---

### 61. Le previsioni contengono copie: le constatazioni vengono prima nella stima

**Decisione.** La stima delle distribuzioni di ritardo si fonda in primo luogo
sulle osservazioni **gia' passate** al momento dell'emissione, e ricorre alle
previsioni solo dove le prime non bastano. Non e' una ponderazione ma un ordine
nella scala di risalita.

**Il fatto misurato.** Quota di terne in cui il ritardo e' **identico al secondo**
a quello della fermata precedente, misurata sui valori grezzi e non sui bin,
perche' due ritardi diversi che cadono nello stesso bin non sono una ripetizione:

| | previsioni | gia' passate |
| --- | ---: | ---: |
| Roma | **22,70%** | 4,45% |
| Torino | 1,26% | 1,30% |

*Fonte: `results/markov_terne.csv`, righe `valori ripetuti (sui secondi)`, colonna
`quota_identiche`, sedici giornate fino al 9 settembre 2026. La prima stesura
riportava 23,07% e 4,66% su quattordici giornate.*

**L'ipotesi che questo doveva mettere alla prova, ed e' stata esclusa.** Le
constatazioni risultavano molto piu' prevedibili delle previsioni: su Torino la
perdita logaritmica senza arco valeva 0,34 bit contro 1,28. Una spiegazione
possibile era che il produttore **congelasse** il ritardo dopo il passaggio,
ripetendolo sulle fermate seguenti: i valori consecutivi sarebbero stati copie e
non osservazioni, l'entropia sarebbe risultata bassa per costruzione, e la
maggiore prevedibilita' delle constatazioni sarebbe stata un artefatto di
propagazione invece che un fatto sul trasporto.

La misura dice l'**opposto**. Su Roma a ripetersi sono le previsioni, cinque volte
piu' delle constatazioni, il che ha una spiegazione semplice: una previsione che
il produttore non ricalcola resta identica, mentre una constatazione registra cio'
che e' accaduto e non ha ragione di coincidere al secondo con quella della fermata
prima. Il congelamento e' quindi escluso, e resta la lettura diretta: **le
constatazioni sono osservazioni migliori**, e la loro maggiore prevedibilita' e'
un fatto sul trasporto.

Va aggiunto che su Torino il fenomeno **non esiste affatto**, 1,3% in entrambe le
popolazioni, ed e' la sesta grandezza su cui i due produttori differiscono in modo
sistematico dopo le cinque della voce 59. Anche qui nella stessa direzione: chi
emette previsioni con due minuti di anticipo non ha il tempo di lasciarle invecchiare.

**La conseguenza sulla stima, che e' la ragione di questa voce.** Su Roma quasi un
quarto delle transizioni osservate fra previsioni e' l'identita', e non perche' il
mezzo abbia mantenuto esattamente lo stesso ritardo ma perche' il valore non e'
stato ricalcolato. Sono **copie, non informazione indipendente**. Stimare la
matrice di transizione pesandole come le constatazioni la spingerebbe verso la
diagonale, e il modello ne uscirebbe convinto che il ritardo cambi meno di quanto
cambi: proprio l'errore che un pianificatore robusto non puo' permettersi, perche'
sottostimerebbe la variabilita' su cui si fonda la sua ragione di esistere.

**Su quante osservazioni il modello poggia davvero.** Le coppie in cui **entrambe**
le osservazioni sono constatazioni sono il **16,5% su Roma** e il **23,3% su
Torino**. Sono numeri diversi sia da quelli delle terne, 10% e 15,6%, sia
dall'attesa, e la differenza ha una ragione: conservando per ogni passaggio
l'ultima osservazione, quella e' la piu' probabile constatazione, e una coppia ne
richiede due mentre una terna tre. Misurarli sulle coppie non era un dettaglio,
perche' e' sulle coppie che la matrice di transizione si stima.

Vale la pena riportarli nel documento come dimensionamento reale: il modello si
fonda su circa **1,7 milioni di transizioni constatate su Roma** e **600 mila su
Torino**, non sui 172 e 18 milioni di righe grezze ne' sui 10 e 2,7 milioni di
passaggi. E' onesto che il lettore sappia su quante osservazioni poggia cio' che
legge.

**Perche' un ordine e non un peso.** Una ponderazione richiederebbe di scegliere
quanto valga una previsione rispetto a una constatazione, e quel numero non lo
sappiamo. L'ordine nella scala di risalita non lo richiede: una cella si stima
sulle constatazioni se ne ha abbastanza; altrimenti si sale a un contesto piu'
grossolano **restando sulle constatazioni**; e solo dopo, se anche li' non
bastano, si ricorre alle previsioni. E' la scelta di preferire un dato migliore a
risoluzione minore rispetto a un dato peggiore a risoluzione piena, ed e'
verificabile: si misura la perdita fuori campione delle due politiche.

**Come si potrebbe verificare.** `quota_valori_ripetuti` in `src/delays/markov.py`,
con il test che ne fissa il comportamento sui secondi invece che sui bin. Sulla
stima, il confronto fra le due politiche di risalita sulla perdita logaritmica di
giornate non usate per stimare: se preferire le constatazioni non migliorasse,
l'ordine si semplifica e questa voce va rivista.

---

### 62. Le celle scoperte non sono traffico scoperto

**Decisione.** Il livello piu' fine della scala di risalita - linea per fascia
oraria per tipo di giorno - si usa su entrambe le citta'. Il modello e' per linea,
non per tipo di linea.

**Alternative considerate.** Ripiegare sul livello per tipo di linea, che la
prima lettura dei conteggi sembrava imporre.

**Il numero che avrebbe portato alla decisione sbagliata.** Alla soglia di venti
osservazioni per cella, le constatazioni coprono il **29,1% delle celle su Roma** e
il **19,9% su Torino**. Guardando solo quello si concluderebbe che il livello fine
non regge: quattro celle su cinque restano senza dati propri.

**Il numero che decide.** Quelle stesse celle coperte servono il **91,5% delle
osservazioni su Roma** e il **98,8% su Torino**. Un quinto della tabella copre
quasi tutto il traffico torinese.

Le due letture divergono perche' una rete di trasporto non e' uniforme: poche
linee portanti concentrano la maggior parte dei passaggi, e molte combinazioni di
linea e fascia oraria corrispondono a servizi marginali che quasi nessuno percorre
- una linea periferica in una fascia morta genera pochissimi passaggi, e la sua
cella resta vuota perche' quel servizio quasi non esiste, non perche' i dati
manchino. La risalita le coprira' senza costo pratico, perche' cio' che copre e'
raro per costruzione.

**Il punto di metodo.** Contare le celle e contare le osservazioni sono due
domande diverse, e su una distribuzione fortemente disuguale danno risposte
opposte. La prima chiede quanta parte della **tabella** si riesce a stimare, la
seconda quanta parte del **fenomeno** si riesce a servire, e il modello esiste per
servire il fenomeno. Riportare la sola quota di celle avrebbe fatto ripiegare su
un modello piu' grossolano di quanto i dati richiedessero, e la perdita di
risoluzione sarebbe stata reale mentre il problema che la motivava non lo era.

**Una conseguenza sulla scelta della soglia.** Alzando la soglia da venti a
cinquanta, Roma scende al **79,8%** delle osservazioni servite mentre Torino resta
al **95,6%**: la soglia pesa molto piu' su Roma. Non e' quindi un parametro da
fissare a un valore tondo per comodita' e uguale per le due citta', e viene tarato
per misura insieme alla concentrazione del priore, con cui forma un solo
meccanismo.

**Come si potrebbe verificare.** `scripts/copertura_constatazioni.py` riporta
entrambe le letture a tre soglie, e la loro divergenza e' visibile a colpo
d'occhio: se un giorno coincidessero, vorrebbe dire che il traffico si e'
uniformato fra le linee.

### 63. Su Torino le constatazioni non esistono, e non e' un dettaglio

**Constatazione, prima della decisione.** GTFS Real-Time non offre alcun segnale di
"il mezzo e' gia' passato": il progetto lo deduce confrontando l'orario atteso -
programmato piu' ritardo - con l'istante in cui il produttore ha pubblicato. La
deduzione presuppone che il produttore pubblichi **anche** le fermate gia' passate.
Nessuno lo aveva verificato.

Non e' vero su Torino. Su tutte e **sedici** le giornate della finestra dichiarata,
il massimo di `timestamp_feed - orario_programmato` vale **fra 0 e 4 secondi**: il
feed torinese toglie la fermata dal `trip_updates` appena il mezzo vi transita, e nel
dato non esiste alcun passaggio avvenuto da osservare. Su Roma lo stesso massimo sta
fra **10.020 e 70.229 secondi**, e il novantanovesimo percentile fra **1.629 e
3.121** in quattordici giornate su sedici: il feed romano continua a pubblicare le
fermate passate per una mezz'ora buona.

**Che cosa contiene allora il gradino "constatazioni" su Torino.** Le righe che
superano il criterio, dal 3,9% all'8,2% a seconda del giorno, sono quelle il cui
orario atteso e' talmente in anticipo da precedere l'istante di pubblicazione. La
prova del nove e' netta: **lo 0,00% di esse ha ritardo positivo, tutti i giorni**, e
il ritardo massimo fra loro e' di **1 secondo**. Non sono passaggi avvenuti: sono
previsioni selezionate per essere molto in anticipo, cioe' una selezione
sistematica e non casuale, che restituisce per costruzione la coda negativa della
distribuzione. Su Roma la stessa quota vale fra il **21,5% e il 35,4%**, e il
massimo arriva a **66.324 secondi**: li' il criterio seleziona davvero dei fatti.

*Fonte: `results/diagnosi_constatazioni.csv`, finestra `2026-09-09`. La prima stesura
di questa voce riportava 69.656 come massimo di feed meno programmato e 59.486 come
ritardo massimo fra le constatazioni romane: il primo era il massimo su quattordici
giornate invece che su sedici, il secondo era il valore dell'ultima giornata e non il
massimo fra le giornate.*

**Due giornate romane fuori riga, da guardare altrove.** Il 31 agosto e il 7
settembre il novantanovesimo percentile romano sale a **31.720 e 36.526 secondi**
contro i circa duemila di tutte le altre, e la quota di righe che superano il
criterio passa dal 2,5% abituale al **17,4% e al 26,2%**. Non tocca questa voce, il
cui verdetto riguarda Torino, ma e' un comportamento del feed romano che nessuna
spiegazione copre, e il 7 settembre e' la stessa giornata che il backtesting della
Fase 5 esclude perche' magra. Va ripreso li'.

**Che cosa questo invalida.** Ogni numero torinese che porti il nome
"constatazioni" descrive quella coda negativa e non la realta' dei ritardi: la
copertura di D1 (19,9% delle celle, 98,8% delle osservazioni al livello fine), il
23,3% di coppie constatate della voce 61, e le stime odierne - 0,379 bit di perdita
su un campione confinato a ritardo non positivo, 3,16 bit sulle previsioni,
correlazione di Pearson 0,240 dentro i bordi dei bin contro 0,999 su tutto. Sono
numeri corretti come calcoli e ingannevoli come misure, perche' la popolazione non
e' quella che il nome promette. Su Roma nulla di tutto questo si applica.

**Il punto di metodo, che vale oltre questo caso.** Il criterio era una deduzione
travestita da osservazione. Era stato verificato che il **calcolo** fosse giusto,
mai che la **premessa** lo fosse, e la premessa riguardava il comportamento di un
produttore esterno su cui non si ha alcun controllo. Il segnale d'allarme non e'
arrivato dal criterio ma da un quantile chiesto per altro: il ritardo massimo fra
le constatazioni torinesi valeva zero, e un massimo esattamente zero non e' un
dato, e' una definizione che si e' chiusa su se stessa. Le statistiche di contorno
- minimo, massimo, quantili estremi - vanno guardate anche quando non servono alla
domanda, perche' sono le uniche che smascherano una popolazione mal definita.

**Alternative aperte, la scelta e' da fare.** (a) Su Torino si stima il modello
sulle previsioni e lo si dichiara, accettando che contengano copie in quantita' non
misurata su quella citta'. (b) Torino esce dal modello dei ritardi e resta solo
dove non ne ha bisogno. (c) Si tenta di ricostruire i passaggi avvenuti dalla
**sparizione** di una fermata dal feed fra due dump consecutivi, che e' l'unico
segnale che il produttore torinese offre, al costo di uno strumento nuovo e di
un'ipotesi ulteriore - che una fermata sparisca perche' e' passata e non per altro.

**Come si potrebbe verificare.** `scripts/diagnosi_constatazioni.py` riporta per
ogni giornata il massimo di `timestamp_feed - orario_programmato`, la quota di
constatazioni e quanta parte di esse abbia ritardo positivo, e pronuncia un
verdetto per citta'. Se un giorno il produttore torinese cominciasse a pubblicare
il passato, il massimo salirebbe di ordini di grandezza e il verdetto si
ribalterebbe da solo.

### 64. I bordi dei bin non si scelgono sulla perdita, e nemmeno sul guadagno

**Decisione.** I bordi sono scelti dal programma confrontando cinque candidati a otto
bin su un **banco di prova tenuto fuori dalla stima**, e la scelta ricade sugli
**ottili**: `(-554, -366, -250, -158, -80, 18, 213)`, i quantili della popolazione di
addestramento al 12,5%, 25%, ..., 87,5%. Restano **gli stessi per le due citta'**,
altrimenti le loro perdite non sarebbero confrontabili e il paragone della voce 59
perderebbe il suo termine di riferimento. La versione precedente di questa voce
sceglieva i `misti` con una metodologia che aveva tre difetti, elencati piu' sotto: i
numeri che seguono sono della corsa corretta, del 10 settembre su quindici giornate
di raccolta (25 agosto - 8 settembre).

**Il difetto che li ha rimessi in discussione.** I bordi originari `(-60, 0, 60, 120,
300, 600, 1200)` erano stati scelti nella Fase 3 sulla popolazione intera, previsioni
comprese. La popolazione su cui si stima e' un'altra, e ha mediana **-139 s** su
Roma: piu' della meta' del campione cadeva sotto il primo bordo, dentro il bin zero,
che e' aperto verso il basso. Misurato: con i bordi vecchi il **62,3%** delle
osservazioni romane e il **45,7%** delle torinesi finivano in uno dei due bin aperti,
dove il modello dichiara di non distinguere nulla.

**Alternative considerate.** Cinque insiemi a otto bin. `attuali`, i vecchi bordi come
termine di paragone. `ottili`, i quantili della popolazione di stima. `centrati`, la
spaziatura degli attuali traslata sulla mediana. `misti`, meta' tagli nell'anticipo e
meta' nel ritardo, per quantili separati. `decisione`, bordi fissi a valori del
problema - `-300, -60, 0, 120, 300, 900, 1800`, da cinque minuti di anticipo a
trenta di ritardo - che non dipendono dai dati e servono da controllo: se un
insieme ancorato a grandezze del problema non regge il confronto con uno adattivo,
la struttura della distribuzione conta piu' dei suoi valori.

**I tre difetti della metodologia precedente.** Il primo giro di scelta conteneva
tre errori di metodo, che sono la ragione per cui i numeri sono cambiati:

1. **La scelta guardava la verifica.** I candidati venivano valutati sulle stesse
   giornate usate poi per misurare il modello finale: un iperparametro scelto sulla
   verifica rende la stima dentro campione. Ora le ultime due giornate di
   addestramento fanno da banco di prova - entrano nella valutazione dei bordi e non
   nella stima che segue - e la verifica non viene toccata dalla scelta. Con meno di
   nove giornate il banco collassa sulla verifica: il programma lo segnala, perche'
   e' una condizione in cui i numeri vanno letti dichiarandola.
2. **La soglia di indistinguibilita' era presa sul massimo fra i candidati.** La
   variabilita' di un candidato dipende dai suoi bordi: usare il massimo fra tutti
   gonfiava o sgonfiava la soglia a seconda di chi capitava in gara. Ora la soglia e'
   la deviazione fra giornate del **riferimento** `attuali`, per citta': 0,0040 bit
   su Roma e 0,0167 su Torino, misurata e non fissata.
3. **I candidati dipendevano dalla popolazione di entrambe le citta'.** Calcolati sul
   campione congiunto, spostavano gli insiemi al variare della popolazione dell'altra
   citta', e le perdite non restavano confrontabili. Ora i candidati che dipendono
   dai dati si calcolano sulla sola prima citta' (Roma), banco escluso: 458.695
   osservazioni su questa corsa.

**Il punto di metodo, che vale piu' della scelta.** *La perdita fuori campione non
puo' decidere questa domanda, e nemmeno il guadagno sul marginale.* Sono due criteri
che sbagliano per costruzione, in versi opposti:

- la **perdita grezza** premia i bordi che ammucchiano massa in pochi bin, perche'
  cosi' l'entropia marginale cala e la perdita con lei, per quanto male il modello
  lavori;
- il **guadagno sul marginale**, cioe' quanto il modello aggiunga a chi non sa nulla,
  corregge quel difetto ma ne introduce uno simmetrico: a numero di bin fisso, i bin
  a frequenza uguale massimizzano l'entropia marginale e quindi il tetto del guadagno.

Nessuno dei due sa che cosa serva al pianificatore. Serve **distinguere secondi**,
dell'ordine di un margine di coincidenza. Si e' misurata quindi anche l'**ampiezza
confusa**: per ciascun bin, la differenza fra il novantanovesimo e l'unesimo
percentile dei ritardi che vi cadono - i secondi che il modello dichiara quando dice
solo "bin b" - mediata sui bin con il peso delle loro numerosita', **ristretta** alle
sole osservazioni fra zero e trenta minuti (0-1800 s), che e' l'orizzonte del margine
di coincidenza. Sono secondi, non bit, e si confrontano con un margine di coincidenza
invece che con un'altra discretizzazione. Il calcolo e' in `risoluzione()` con
`ristretto=(0, 1800)`; la colonna nel CSV e' `ampiezza_confusa_decisione`.

| bordi | guadagno Roma | guadagno Torino | massa nei bin aperti | ampiezza confusa 0-30 min |
| --- | ---: | ---: | ---: | ---: |
| attuali | 1,407 | 1,227 | 62,3% / 45,7% | 201 s / 122 s |
| ottili | **2,072** | **1,541** | 23,4% / 8,1% | 701 s / 368 s |
| centrati | 1,793 | 1,078 | 15,5% / 2,4% | 417 s / 275 s |
| misti | 2,006 | 1,444 | 17,2% / 3,2% | 309 s / 201 s |
| decisione | 1,787 | 1,338 | 28,2% / 9,9% | 293 s / 184 s |

La regola usa il guadagno per **escludere** e i secondi per decidere: un candidato e'
ammesso se il suo guadagno, in **ciascuna** citta', non dista dal migliore piu' della
soglia di quella citta'; fra gli ammessi vince quello che confonde meno secondi. Su
questa corsa solo gli **ottili** superano l'esclusione - misti resta indietro di
0,066 bit su Roma (2,0717 contro 2,0061) e di 0,097 bit su Torino (1,5406 contro
1,4438), oltre le soglie di 0,0040 e 0,0167 - e la scelta ricade su di loro
senza che i secondi decidano nulla. E' un esito onesto della regola, non una sua
conferma: con dati diversi la regola potrebbe pronunciare un vincitore diverso, e va
riletta a ogni riacquisto dei dati.

**Perche' gli ottili hanno vinto stavolta.** Il guadagno li premia per costruzione -
bin a frequenza uguale massimizzano il tetto - ma i loro numeri su questa corsa sono
forti anche dove la tautologia non arriva: la massa nei bin aperti scende al 23,4% e
all'8,1%, contro il 62,3% e il 45,7% degli attuali. Il difetto noto degli ottili -
tutti i tagli nell'anticipo, un solo bin aperto sopra i due minuti di ritardo - qui
non si presenta nella forma estrema di prima: l'ultimo bordo e' a +213 s, e il lato
del ritardo, quello a cui `P(arrivo <= T)` e' sensibile, ha tre bin risolti. Va pero'
dichiarato che i loro quantili sono calcolati sulla sola Roma, la cui distribuzione
ha una coda di anticipo molto piu' lunga di Torino: su Torino gli ottili romani
producono comunque il guadagno migliore fra i candidati, 1,541 bit.

**Come si potrebbe verificare.** `python scripts/stima_rete.py --bordi misura`
ricalcola la tabella e ripronuncia la scelta; `--bordi attuali` rifa' la stima coi
vecchi bordi. Se un giorno la distribuzione dei ritardi si spostasse, i candidati che
dipendono dai dati si spostano con lei e la scelta si rifa' da sola. La separazione
fra banco e verifica e' verificabile a mano: le giornate del banco sono `bordo_holdout`
(ultime due di addestramento) e non compaiono in `stima`.

**Due limiti di questa scelta, dichiarati.** *Il primo riguarda la soglia.* La
deviazione che la fissa e' calcolata su **due sole giornate di banco**, e vale 0,0040
bit su Roma e 0,0167 su Torino: e' la variabilita' fra due giorni, non quella del
regime di verifica, dove la stessa quantita' misurata sulla scala principale vale
+-0,0625 bit. La soglia piccola rende l'esclusione severa: a parita' di dati, la
scelta non cambia per alcuna soglia fino a 0,066 bit su Roma e 0,097 su Torino, cioe'
finche' il secondo candidato (misti) resta escluso; oltre quel valore misti rientra in
gara e i secondi lo scavalcano sugli ottili (309 s contro 701). La severita' e' quindi
una conseguenza del banco corto, non una proprieta' robusta della regola. *Il secondo
riguarda il criterio.* Se si normalizza la perdita per l'entropia marginale propria di
ciascun candidato - il rapporto fra quanto il modello perde e quanto c'e' da perdere
con quei bordi - gli ottili sono **ultimi ex aequo** su Roma (0,3074 contro 0,2785 del
`decisione`) e quartultimi su Torino, e il candidato `decisione` confonde **2,4 volte
meno secondi** (293 s contro 701). La scelta fra guadagno assoluto e perdita relativa
non e' neutra: e' la stessa domanda aperta che la voce 64 aveva posto sui criteri, e
rimane aperta. Si rimette alla sola misura che puo' chiuderla, cioe' il confronto fra
`--bordi ottili` e `--bordi decisione` nel regime in cui la decisione si applica - il
backtesting della Fase 5, dove la grandezza che conta non e' piu' la perdita sui bin ma
le coincidenze perse a parita' di tempo nominale. Fino a quella misura questa scelta va
letta come provvisoria: gli ottili sono i bordi con cui si lavora, non i bordi che il
metodo ha dimostrato migliori.

**Su quale popolazione stanno i quantili degli ottili.** I candidati che dipendono dai
dati si calcolano sulla **sola Roma e sulla sola popolazione di stima**, cioe' le
constatazioni: 458.695 osservazioni su questa corsa, banco escluso. La verifica finale
percorre anche la popolazione `tutte`, dove l'entropia marginale e' piu' bassa (2,951
bit contro 2,998) perche' le previsioni si addensano in meno bin: chi legge una perdita
su `tutte` deve sapere che il tetto di quella colonna non e' lo stesso della principale.

**Glossario colonne `results/stima_rete.csv`.** Una riga per colonna, popolazione e
confrontabilita':

- `perdita`: perdita media fuori campione (bit) sulla popolazione di verifica usata per
  la stima (Roma: constatazioni, Torino: tutte). Confrontabile fra scale diverse della
  stessa citta'.
- `perdita_previsioni`: perdita sulla popolazione complementare a quella di stima (Roma:
  previsioni, Torino: non esiste). Serve come secondo campione out-of-sample, non e' la
  perdita principale.
- `raffronto_tutte_perdita`: perdita su **tutte le coppie** di verifica (Roma:
  constatazioni+previsioni insieme). E' la riga di raffronto per il paragone con Torino,
  che non ha due popolazioni.
- `guadagno`: `entropia_marginale - perdita`. Grandezza confrontabile fra bordi diversi.
- `entropia_marginale`: entropia del modello che ignora tutto (nessun contesto, nessun
  ritardo a monte). Tetto della perdita, dipende dai bordi.
- `coppie_stima`: numero di coppie usate per stimare la matrice con i bordi dati.
  Dipende dalla popolazione di stima e dalla finestra addestramento+taratura.
- `scarto_calibrazione`: scarto medio fra perdita prevista e perdita osservata per
  giornata di verifica. Misura la calibrazione del modello.
- `correlazione_implicita`: correlazione implicita nella matrice di transizione stimata.
  Si confronta con la correlazione 0,70 della Fase 4.

**Numeri superati da non riusare.** Questi numeri appartengono a esecuzioni precedenti
con metodologia o dati diversi e vanno scartati dal documento:

- `0,6171`: perdita precedente ai bordi rifatti (voce 64 prima correzione).
- `0,0012`: deviazione precedente alla separazione banco/verifica.
- `Pearson +0,885`: correlazione precedente alla correzione della popolazione torinese
  (voce 63).

**CHIUSURA: la Fase 5 ha risposto, e i due insiemi sono indistinguibili.** Questa
voce rimetteva al backtesting la scelta fra `ottili` e `decisione`. Il backtesting
ha risposto **no, non cambia i risultati**, e la ragione per cui sembrava
cambiarli e' essa stessa misurata.

Sul primo giro i due insiemi parevano distinguersi: a quindici minuti di margine
`decisione` dava +11,1 punti di viaggi arrivati entro la scadenza e `ottili`
+7,5. La differenza veniva **per intero da una giornata**: Roma 2026-09-07, che il
consolidamento aveva prodotto parziale, contribuiva sette coppie invece di trenta
e pesava nella media fra giornate quanto le altre. Escludendola con la regola
dichiarata al punto seguente, i due insiemi danno **+10,0 punti entrambi**, e le
deviazioni si stringono da +/-3,5 e +/-10,4 a +/-1,9 per tutti e due.

| margine | `decisione` | `ottili` |
| ---: | ---: | ---: |
| 10 min | +4,4 | +3,3 |
| **15 min** | **+10,0** | **+10,0** |
| 20 min | +13,3 | +14,4 |
| 30 min | +10,0 | +10,0 |

Restano differenze di uno o due punti a venti minuti, dentro le deviazioni. **La
scelta dei bordi non e' un punto di decisione del progetto**: si adottano gli
`ottili`, che vincevano sul guadagno, e si dichiara che `decisione` avrebbe dato
gli stessi risultati. Il lavoro di misura che ha portato qui non e' sprecato: ha
stabilito che i bordi vecchi erano sbagliati - due terzi della massa romana in un
bin aperto - e che fra i candidati ragionevoli la scelta e' indifferente. Sono due
conclusioni diverse, e solo la prima richiedeva una decisione.

**La regola sulle giornate magre, fissata prima di guardarne l'esito.** Una
giornata che contribuisca **meno della meta' delle coppie richieste** non entra
nelle medie. La media fra giornate le pesa tutte uguali, ed e' la scelta giusta -
le istanze di uno stesso giorno condividono il traffico di quel giorno e non sono
indipendenti - ma ne segue che sette coppie contano quanto trenta, e sette coppie
sono un campione che il caso muove a piacere. La soglia e' a meta' perche' e' il
valore che separa "giornata incompleta" da "giornata con qualche buco" senza
doversi chiedere quale risultato produca, ed e' stata scelta prima di calcolarlo.
Sui dati raccolti esclude una sola giornata, dichiarata accanto ai risultati
romani, e il codice la stampa a ogni esecuzione
(`scripts/backtest.py`, `QUOTA_MINIMA_DI_COPPIE`).

---

### 65. Su Torino il dato non e' un ritardo osservato, ed e' un solo dato

**Decisione.** Su Torino cade la seconda dimensione della scala di risalita. Non si
stima piu' su "constatazioni" con le previsioni a fare da priore: si stima su
**un'unica popolazione**, tutte le coppie, con la sola dimensione del contesto.
Cambia anche il nome di cio' che si stima, e va scritto come si legge:

> su Torino il ritardo non e' mai osservato come fatto compiuto. Il dato e'
> l'**ultima stima del produttore** prima che la fermata sparisca dal feed, emessa
> con una mediana di circa due minuti di anticipo.

Su Roma la scala a due dimensioni resta, perche' li' la distinzione fra fatto e
previsione e' reale.

**Alternative considerate.** (a) Stimare su Torino "sulle previsioni invece che
sulle constatazioni": formulazione sbagliata, perche' presuppone due popolazioni di
cui una si scarta, mentre ce n'e' una sola e la distinzione collassa. (b) Togliere
Torino dal modello dei ritardi: farebbe perdere la seconda citta' e con essa il
criterio di generalita' su cui il progetto e' valutato. (c) Ricostruire i passaggi
avvenuti dalla **sparizione** di una fermata dal feed fra due dump consecutivi: e'
l'unico segnale che quel produttore offre, ma i nostri stessi dati lo indeboliscono,
perche' su 288 corse torinesi presenti in due dump distanti 130 risultavano
accorciate e **113 allungate**. Se le liste crescono e calano, la sparizione non e'
un segnale pulito di passaggio, e costruirci sopra uno strumento nuovo e' spesa a
rischio.

**Motivo.** L'estrazione non cambia di una riga: `ultima_revisione` tiene gia'
l'ultima pubblicazione di ciascun passaggio, che su Torino e' esattamente la stima
piu' vicina al transito. Cio' che cambia e' smettere di chiamare "constatazioni" un
quarto di quelle righe e di trattarle a parte. Quel quarto non era una popolazione
ma il risultato di una selezione sistematica - le previsioni tanto anticipate da
precedere l'istante di pubblicazione - e separarlo significava stimare sulla coda
negativa della distribuzione chiamandola realta'.

**Che cosa la riformulazione ha rimesso a posto.** Le quattro letture della
correlazione, che sulla popolazione fasulla si contraddicevano - Pearson +0,999 su
tutto contro +0,240 dentro i bordi - ora concordano: **+0,908, +0,936, +0,923,
+0,879**, con la matrice a +0,907. Una popolazione mal definita si riconosce anche
cosi', dal fatto che misure che dovrebbero dire quasi la stessa cosa non la dicono.

**La tabella che entra nel documento.** Quella della voce 59 - le sei grandezze
misurate sui due produttori - e' la tabella di riferimento per questa voce e per il
paragrafo del documento che descrive Torino: in particolare la sesta riga, "fin dove
nel passato arriva il feed" (Roma 70.229 s, Torino **4 s**), e' quella che fonda la
dichiarazione con cui ogni numero torinese va letto, cioe' che li si verifica contro la
stima del produttore a circa due minuti e non contro un transito osservato.

**Come si potrebbe verificare.** La scelta e' fatta dal codice sui dati, non
scritta a mano: `Citta.scale` guarda il massimo di `timestamp_feed -
orario_programmato` e passa a una sola dimensione sotto la soglia. Se il produttore
torinese cominciasse a pubblicare le fermate passate, la scala tornerebbe a due
dimensioni da sola. `--scala due-dimensioni` forza il comportamento precedente, per
riprodurre i numeri anteriori a questa voce.

---

### 66. I candidati di bordi si calcolano su una citta' sola, e la finestra si fissa

**Decisione.** Due scelte di contorno alla scelta dei bordi, entrambe di
separazione. La prima: i candidati che dipendono dai dati (`ottili`, `centrati`,
`misti`) si calcolano sul campione della **sola Roma**, banco di prova escluso - non
sul campione congiunto delle due citta'. La seconda: l'etichetta della finestra di
stima, la data da passare a `--fino-a`, la stampa un programma
(`scripts/etichetta_finestra.py`) che restituisce l'ultima giornata disponibile per
**tutte** le citta', non la piu' recente in assoluto.

**Alternative considerate.** Per i candidati: il campione congiunto, cioe' come si era
fatto nel primo giro; oppure calcolarli citta' per citta', con bordi diversi. Per la
finestra: lasciare che l'esecuzione prenda sempre l'ultimo giorno disponibile.

**Motivo.** Il campione congiunto rendeva gli insiemi candidati dipendenti dalla
popolazione di entrambe le citta': ricalcolare con una popolazione diversa spostava i
bordi e rompeva la confrontabilita' delle perdite fra due esecuzioni, che e' cio' su
cui poggia il paragone della voce 59. Calcolarli citta' per citta' avrebbe dato bordi
diversi alle due citta', ed e' esattamente cio' che la voce 64 vieta. La prima citta'
(Roma) e' quella con la popolazione di stima piu' ampia e meglio definita: usarla
come riferimento rende i candidati stabili al variare dell'altra. Sulla finestra: la
raccolta continua mentre si misura, e due esecuzioni a distanza di giorni cadono su
giornate diverse; senza un'etichetta fissa un confronto fra due giri attribuirebbe
alla correzione metodologica uno spostamento che e' solo un giorno nuovo. Prendere
l'ultima giornata disponibile per tutte evita anche il caso in cui una citta' abbia
un giorno in piu' a meta': la finestra comune e' `min` delle ultime giornate.

**Come si potrebbe verificare.** Due esecuzioni dello stesso script con lo stesso
`--fino-a` devono produrre insiemi candidati identici; due senza, su finestre diverse,
devono produrne di diversi (e la differenza va attribuita alla finestra, non al
metodo). `scripts/etichetta_finestra.py` si confronta a mano con `ls
data/processed/osservazioni/*`.

### 67. `Tratta` riceve `sequenza_a_monte`: un'interfaccia congelata e riaperta

**Decisione.** Il contratto `Tratta`, fissato in Fase 2 e da allora intoccato,
acquista un campo: `sequenza_a_monte: int | None = None`, la posizione lungo la
corsa dell'ultima fermata gia' servita. Va **in coda e con valore predefinito**,
esattamente come vi era entrato `ritardo_a_monte`, cosi' ogni chiamata esistente
continua a valere senza modifiche.

**Perche' si riapre qualcosa che era stato chiuso.** La Fase 2 aveva congelato
l'interfaccia proprio per non doverla inseguire, e il ragionamento e' registrato nel
docstring di `src/delays/interfaccia.py`. La Fase 5 chiede pero' una cosa che nel
congelare non era stata prevista: nel backtesting il modello viene interrogato **a
meta' viaggio**, quando il viaggiatore e' gia' a bordo, e in quel momento si sa non
solo *quanto* fosse il ritardo all'ultima fermata osservata ma anche *dove* quella
fermata stesse lungo la corsa. Le due informazioni non sono la stessa: un ritardo di
tre minuti alla seconda fermata e uno alla ventesima dicono cose diverse, perche' nel
primo caso restano diciotto fermate per accumularne o recuperarne, nel secondo nessuna.

**Alternative considerate.** Ricavare la posizione da `stop_sequence`, che nella
`Tratta` c'e' gia': dice pero' dove si arriva, non da dove si e' osservato, e le due
coincidono solo se il ritardo a monte viene dalla fermata immediatamente precedente -
vero nel modello attuale, non necessariamente nel prossimo. Codificare le due cose in
un campo solo: costringerebbe chi chiama a conoscerne la codifica, che e' il contrario
di un'interfaccia.

**Motivo per cui si annota invece di farlo e basta.** Una modifica retrocompatibile non
rompe nulla, ed e' proprio per questo che va scritta: non lasciando traccia nei test ne'
negli errori, fra sei mesi il campo sembrerebbe esserci sempre stato, e la ragione per
cui l'interfaccia era stata congelata sembrerebbe non essere mai esistita. Il campo
**non e' ancora usato** dal modello stimato, che condiziona su linea, fascia, tipo di
giorno e bin del ritardo a monte: sta li' perche' la Fase 5 possa passarlo senza dover
riaprire di nuovo il contratto.

**Come si potrebbe verificare.** I test in `tests/test_planner.py` costruiscono `Tratta`
senza il campo nuovo e devono continuare a passare: se un giorno diventasse
obbligatorio, fallirebbero tutti insieme e la retrocompatibilita' si scoprirebbe rotta
prima di essere pubblicata.

---

### 68. Il modello appreso incontra il pianificatore: che cosa si assume dentro un bin

**Decisione.** `src/delays/bayesiano.py` traduce la tabella di Fase 3 nel contratto
fissato in Fase 2. Dentro ciascun bin si assume la distribuzione di **massima
entropia** compatibile con cio' che si e' misurato: uniforme nei bin limitati, dove si
conosce solo l'intervallo; esponenziale nei due bin aperti verso l'infinito, dove
all'intervallo si aggiunge il ritardo medio misurato dentro quel bin.

**Alternative considerate.** Concentrare la massa di ogni bin nel suo valore medio: la
ripartizione diventerebbe una scala a gradini e `P(arrivo <= T)` salterebbe di colpo al
variare di T di un secondo - non un difetto di precisione ma un artefatto, che il
pianificatore prenderebbe per un fatto e su cui sceglierebbe. Assegnare ai bin aperti
un'ampiezza convenzionale, per esempio il doppio dell'ultimo bordo: inventerebbe il
parametro che pesa di piu', dato che i bin aperti raccolgono fra un quinto e due terzi
della massa a seconda dei bordi (voce 64).

**Motivo.** L'assunzione dentro il bin non e' un dettaglio implementativo: e' l'unico
punto in cui il progetto aggiunge informazione che i dati non contengono, e per questo
va scelta col criterio che ne aggiunge il meno possibile. La massima entropia e'
esattamente quel criterio, e ha il pregio di non lasciare parametri liberi: gli estremi
vengono dai bordi tarati, le medie dalle stesse giornate su cui si stima.

**Che cosa succede quando manca il contesto.** Alla prima fermata di un itinerario il
ritardo a monte non esiste ancora: non si sceglie un bin arbitrario, si
**marginalizza** sulla distribuzione dei bin a monte misurata sulle giornate di stima,
che e' cio' che una rete bayesiana fa su una variabile non osservata. Una linea mai
vista nelle giornate di stima ripiega sul livello piu' grossolano della scala di
risalita - il caso per cui la scala esiste - e i ripieghi si contano e si riportano
invece di restare invisibili.

**Come si potrebbe verificare.** `tests/test_bayesiano.py` controlla le proprieta' che
una distribuzione deve avere in quanto tale: ripartizione monotona fra zero e uno,
quantile che la inverte, campione che la riproduce. Le due assunzioni hanno ciascuna il
proprio test: l'uniforme si vede dalla ripartizione lineare a tratti dentro un bin
limitato, l'esponenziale dal fatto che la media della coda sia quella misurata e non
un'altra.

---

### 69. Il backtesting rigioca, non chiede al modello di giudicare se stesso

**Decisione.** Il confronto fra le due strategie - arrivo minimo teorico contro massimo
`P(arrivo <= T)` - non si fa confrontando le probabilita' che il modello attribuisce,
ma **rigiocando entrambe le scelte sui ritardi che quel giorno sono stati osservati** e
contando chi arriva entro la scadenza.

**Alternative considerate.** Confrontare la probabilita' attesa delle due scelte, che e'
cio' che `scripts/pianificazione_robusta.py` misura in Fase 4. E' una misura legittima
di quanto la frontiera sia varia, ma non risponde alla domanda di ricerca: la
probabilita' che il modello attribuisce alla propria scelta e' per costruzione la piu'
alta - e' quella che ha scelto - e misurarla non dice quanti viaggi riescano davvero.
Il modello sarebbe insieme giudice e imputato.

**Motivo, e la cosa che solo la replica vede.** Rigiocare sugli orari reali fa emergere
un fenomeno che l'orario teorico dichiara sempre riuscito: **il mezzo in anticipo fa
perdere la coincidenza esattamente come quello in ritardo**. Se la corsa successiva
parte novanta secondi prima del previsto e il viaggiatore arriva puntuale, la
coincidenza e' persa, e nessun confronto fatto sull'orario programmato puo'
accorgersene.

**Tre scelte di misura, da dichiarare.**

1. **I recuperi contano come coincidenze perse, non come fallimenti.** Ogni tappa porta
   con se' le corse successive della stessa linea: se la pianificata sfugge si prende la
   seguente e si arriva piu' tardi. Trattare la coincidenza persa come fallimento del
   viaggio sopravvaluterebbe la differenza fra le strategie, perche' in una rete urbana
   una linea ripassa.
2. **Un viaggio interrotto non e' arrivato entro la scadenza.** Escluderlo dal conto, o
   contarlo riuscito, premierebbe la strategia che si caccia piu' spesso nei guai.
3. **Una tratta non osservata ferma la replica**, e non viene sostituita con l'orario
   teorico: sarebbe dichiarare puntuale cio' che non si e' visto, e proprio nei casi in
   cui il dato manca.

**Il numero senza il quale il risultato non si legge.** Dove le due strategie scelgono
lo stesso itinerario la differenza fra loro e' zero **per costruzione**, e mediare su
quelle istanze diluisce l'effetto verso lo zero per quanto il modello sia bravo. Si
riporta quindi la quota di istanze in cui le due divergono, e la differenza calcolata
sulle sole divergenti: senza, un vantaggio inesistente e un vantaggio reale ma raro si
leggono allo stesso modo.

**I numeri pubblicabili sono solo quelli della corsa definitiva.** Durante lo
sviluppo una corsa pilota - otto coppie, la sola Torino - aveva prodotto un 3,4% di
viaggi incompleti e una divergenza del 35,9%: sono stati riportati, e sono falsi. I
valori della corsa definitiva, in `results/backtest.csv`, sono **5,53%** di viaggi
incompleti e una divergenza che va dal **7,5% al 35,0%** a seconda del margine, con
media 24,0%. Il CSV del pilota non esiste piu', quindi i suoi numeri non sono
verificabili da nessuno e non possono comparire da nessuna parte. Vedere la voce 70.

**Un limite della selezione, misurato.** Solo una parte delle corse dell'orario compare
nel tempo reale, quindi non ogni itinerario e' rigiocabile: si tengono le coppie con
almeno due candidati interamente osservati, e sulla giornata di prova sono circa quattro
su dieci dei candidati - il 38,4% su Roma e il 36,5% su Torino, misurati sul 9
settembre. E' una selezione che favorisce le linee frequenti, e la quota si riporta
accanto ai risultati invece di restare implicita.

**Come si potrebbe verificare.** `tests/test_replica.py` costruisce itinerari di cui si
conosce l'esito - la coincidenza persa per anticipo, quella tenuta per un soffio, quella
persa per un secondo, il recupero riuscito, l'interruzione - e verifica che la replica li
ritrovi. Il caso del mezzo in anticipo ha un test proprio, perche' e' il fenomeno su cui
poggia l'intera domanda di ricerca.

### 70. Un numero scritto a memoria non fallisce nessun test

**Constatazione.** Nel resoconto della Fase 5 due numeri erano sbagliati: il
**3,4%** di viaggi incompleti e il **35,9%** di divergenza fra le strategie. I
valori giusti, letti dal CSV della corsa definitiva, sono **5,53%** e una
divergenza che va dal **7,5% al 35,0%** a seconda del margine, con media 24,0%.
I due numeri sbagliati venivano da una corsa pilota - otto coppie, la sola
Torino, i soli bordi `ottili` - il cui CSV era stato cancellato prima della corsa
vera. Erano corretti quando furono scritti, e sono diventati falsi quando la
corsa che li sosteneva e' stata sostituita.

**Perche' questo e' il difetto piu' importante fra quelli trovati**, e non per la
sua gravita'. Nessun test poteva accorgersene: i numeri stavano in un messaggio,
non in un file, e il file da cui venivano non esisteva piu'. La suite era verde,
il CSV era pulito, la replica era deterministica, e il numero era sbagliato lo
stesso. E' il modo di sbagliare tipico della fase che viene - il documento - dove
si riportano centinaia di numeri e nessuno di essi e' eseguibile.

**Decisione.** Tre regole, in ordine di forza.

1. **Un numero si rilegge dal file ogni volta che lo si riscrive.** Non si cita a
   memoria un risultato prodotto da una corsa precedente, nemmeno quando lo si e'
   scritto poche ore prima: fra le due scritture puo' esserci stata una corsa
   nuova, ed e' esattamente quello che era successo.
2. **Un numero pubblicabile viene da un CSV in `results/`.** Le corse pilota, i
   giri di prova e le esecuzioni parziali producono numeri veri ma non
   pubblicabili, e i loro file non sopravvivono: quindi i loro numeri non possono
   comparire da nessuna parte. La voce 69 riporta soltanto quelli della corsa
   definitiva.
3. **`scripts/verifica_numeri.py` setaccia il documento** e per ogni numero cerca
   una cella nei CSV che vi corrisponda alla precisione con cui e' scritto. Non e'
   un verificatore: i falsi positivi - anni, conteggi, numeri citati dalla
   bibliografia - sono previsti e si guardano a occhio. Serve a rendere
   impossibile la cosa opposta, cioe' che un numero senza origine passi
   inosservato.

**Alternative considerate.** Fidarsi della rilettura a mano: e' cio' che si e'
fatto finora, e ha lasciato passare due numeri su un resoconto di venti righe.
Vietare le corse pilota: si perderebbe il modo piu' economico di scoprire che una
pipeline non funziona, e il problema non e' il pilota ma il fatto che i suoi
numeri sopravvivano al suo file.

**Come si potrebbe verificare.** `python scripts/verifica_numeri.py` sul documento:
ogni riga `NON TROVATO` e' un numero da giustificare o da togliere. La prova che
il setaccio funzioni e' che, rimettendo nel documento il 3,4% e il 35,9%, li
segnali entrambi.

### 71. La provenienza si dichiara sotto la tabella, non si cerca dopo

**Decisione.** Ogni tabella di risultati del documento porta sotto di se' una riga
che dice da quale CSV viene e con quale aggregazione. Per esempio:

> *Fonte: `results/ricerca_astar.csv`, medie sulle sole coppie risolte (43 su 50 a
> Roma, 39 su 50 a Torino).*

**Perche' questa e non un verificatore migliore.** La voce 70 aveva messo un
setaccio a guardia dei numeri del documento. Misurandone il potere si e' scoperto
che non puo' averne: il **60,8%** delle percentuali inventate a un decimale trova
comunque una corrispondenza fra le celle dei riepiloghi, e col dettaglio incluso si
arriva al 99,5%. Non e' un difetto dell'implementazione ma un limite di
informazione - una percentuale a un decimale ha mille valori possibili e il corpus
ne contiene migliaia - e nessun raffinamento lo toglie. Ne segue che i numeri che
il setaccio dichiara "trovati" non sono verificati, e che inseguire quelli non
trovati costa molto e conclude poco.

La riga di fonte fa tre cose che il setaccio non puo' fare. **Rende il numero
rifacibile** da chiunque abbia il repository, perche' dice il file e l'operazione.
**Obbliga chi scrive a riaprire il file** invece di citare a memoria, che e'
esattamente il difetto della voce 70: il 3,4% era vero quando fu scritto ed e'
diventato falso quando la corsa che lo sosteneva e' stata sostituita. E
**trasforma il controllo da indovinello in verifica**, perche' il lettore non deve
cercare il numero: gli viene detto dove sta.

**Alternative considerate.** Un verificatore piu' fine, che ricostruisca gli
aggregati: e' stato provato, porta i falsi positivi da 112 a 67 su 920 numeri e
lascia il tasso di falso dove sta. Esportare ogni numero del documento da un
programma, in stile *literate programming*: risolverebbe il problema alla radice ma
riscriverebbe il documento in un formato che il modello di consegna non prevede.

**Il setaccio resta, con un ruolo piu' modesto.** Serve sui numeri **in prosa**,
che nessuna riga di fonte copre, e a segnalare quelli che nessun CSV sostiene -
che e' come si sono scoperti i numeri della rete ASP a piena scala, esistenti solo
nel log di una esecuzione. Il programma dichiara il proprio tasso di falso a ogni
esecuzione, perche' chi lo legge sappia quanto vale un "trovato".

**Quando un numero non ha un CSV: si dichiara, non si toglie.** Alcuni numeri del
documento non sono rifacibili e non lo saranno mai, perche' misurano una condizione
passata, dati da allora potati, o il comportamento di un'implementazione che e' stata
rimossa. Toglierli impoverirebbe il documento di cio' che ha davvero deciso le scelte;
lasciarli senza segno li farebbe sembrare verificabili come gli altri. Vanno percio'
marcati in chiaro come **misura una tantum, con la data in cui fu presa**, al posto
della riga di fonte:

> *Misura una tantum del 26 agosto 2026: l'implementazione che la produceva e' stata
> sostituita e nessun CSV la sostiene.*

La data non e' un ornamento: dice al lettore che quel numero descrive i dati e il
codice di quel giorno, e che la distanza fra quella data e oggi e' la misura di quanto
vada preso con cautela. La regola vale in entrambi i versi: un numero **senza** quel
marchio deve avere una riga di fonte, e uno **con** quel marchio non va rigenerato
accidentalmente da un'esecuzione nuova, perche' non sarebbe la stessa misura.

Le quattro misure che nel documento portano questo marchio sono: le 288 corse torinesi
in due dump distanti (9 settembre 2026), i 4.691 passaggi contro 13.092 della chiave
naturale (26 agosto 2026), i 48,5 MB dell'archivio romano e i 59 byte del suo `.md5`
(25 agosto 2026), e le correlazioni +0,999 e +0,240 della popolazione torinese poi
abbandonata (9 settembre 2026).

**Come si potrebbe verificare.** Prendere una tabella a caso del documento, leggere
la sua riga di fonte, ed eseguire cio' che dice. Se il numero non viene fuori, o la
riga e' sbagliata o il numero lo e'.

---

### 72. Le cifre del CSV nelle tabelle, il numero arrotondato in prosa

**Decisione.** Nelle tabelle i risultati si riportano **con le cifre che hanno nel
CSV**: `0,4664`, non `46,6%`. In prosa si scrive il numero arrotondato e si rimanda
alla tabella: *"circa il 47%"*. Le due forme non si scambiano.

**Motivo, misurato.** Un numero a quattro decimali cercato fra le celle dei
riepiloghi ha un tasso di falsa corrispondenza del **14,5%**; la stessa grandezza
scritta come percentuale a un decimale arriva al **60,8%**, e un intero a cinque
cifre allo **0,0%**. Le cifre non sono un vezzo tipografico: sono l'unica cosa che
rende un numero verificabile. Scritto "46,6%" non lo e' da nessuno, nemmeno da chi
lo ha prodotto.

La prosa ha il problema opposto: quattro decimali in mezzo a una frase non si
leggono, e una pagina di cifre non si discute. Per questo l'arrotondamento in prosa
non e' una concessione ma la scelta giusta **purche' la tabella accanto porti il
valore pieno**, e purche' il testo rimandi alla tabella invece di fingere di essere
esso stesso la fonte.

**Alternative considerate.** Cifre piene ovunque: rende il testo illeggibile e non
aggiunge verificabilita', perche' la tabella c'e' gia'. Percentuali ovunque, anche
in tabella: e' la pratica corrente in molti lavori, e rende il documento
inverificabile senza che nulla lo segnali - il caso peggiore.

**Come si potrebbe verificare.** `scripts/verifica_numeri.py` stampa il tasso di
falso per ciascuna forma a ogni esecuzione: se un giorno le tabelle fossero scritte
in percentuale, il tasso sulle percentuali smetterebbe di essere una curiosita' e
diventerebbe la misura di quanto il documento sia controllabile.

### 73. L'archivio dell'orario e' un parametro, non un dettaglio dell'esecuzione

**Decisione.** Gli script che misurano sul grafo statico ricevono `--archivio` e
scrivono la colonna `archivio` nel CSV. La funzione che sceglie l'archivio sta in
un posto solo, `src.gtfs.loader.archivio_in_vigore`. Tutte le misure statiche del
progetto sono rifatte sull'archivio del **26 agosto**, sulla stessa macchina.

**Il difetto.** Quattro script - `ricerca_confronto`, `pianificazione_robusta`,
`csp_greedy`, `complessita_kb` - avevano quattro copie identiche di una funzione
che prendeva sempre l'**ultimo archivio disponibile**. L'orario cambia ogni giorno:
ne seguiva che ogni fase aveva misurato sulla rete in vigore il giorno in cui era
stata eseguita, e che nessun CSV lo registrava. Dal 27 agosto Roma ha 8.300
fermate invece di 8.301, quindi il documento avrebbe potuto dire 8.301 in un
capitolo e usarne 8.300 nel successivo senza che nulla lo segnalasse. E' lo stesso
difetto della finestra delle Fasi 3 e 5, su un altro parametro: un valore lasciato
implicito perche' "tanto e' sempre l'ultimo".

**Che cosa e' cambiato rigenerando: niente.** Il confronto riga per riga con le
versioni precedenti:

| CSV | righe | differenze sui conteggi |
| --- | ---: | ---: |
| `complessita_kb` | 78 | 0 |
| `ricerca_astar` | 500 | 0 |
| `grafo_finestra` | 30 | 0 |
| `velocita_archi` | 2 | 0 |
| `robusto_griglia_T` | 1.920 | 0 |
| `conv_vs_montecarlo` | 1.088 | 0 |

Restano diversi i soli tempi di esecuzione, e di poco. Il rischio era reale e non
si e' materializzato: tutte le fasi stavano gia' sullo stesso archivio.

**La scoperta che rende la voce onesta.** Prima di rigenerare, l'archivio di
ciascun CSV era stato **dedotto dalla data del commit**, ed era una deduzione
sbagliata: `robusto_griglia_T`, committato il 27 agosto, stava gia' sull'archivio
del 26. Il metodo giusto e' stato un altro: contare le fermate fisiche in ogni
archivio e vedere quale desse 8.301 - lo danno il 25 e il 26, dal 27 sono 8.300.
Dedurre la provenienza di un numero da quando e' stato committato **sembra**
rigoroso, e qui avrebbe fatto rigenerare un file per correggere un difetto che non
aveva.

**Lo stesso meccanismo su un altro parametro: i 500 m/s.** Rifacendo l'esperimento
sulla chiave di stato (voce 70, numeri senza file) il programma usava una velocita'
massima di 500 m/s, scelta perche' sembrava un limite superiore neutro. Dava
1.512.712 stati contro i 1.464.312 del documento: un esperimento diverso invece di
una verifica. Con la velocita' **misurata** da `velocita_archi.csv`, 139,12 m/s, i
numeri coincidono esattamente. Un parametro scelto per comodita' basta a rendere
irriproducibile un numero che era giusto, e il fatto che sembri neutro non lo rende
tale.

**Un'eccezione voluta.** `backtest.py` non riceve `--archivio`: usa
`archivio_per(citta, giornata)`, cioe' l'archivio in vigore nella giornata che
rigioca. Li' fissarlo sarebbe l'errore opposto - farebbe conoscere al pianificatore
un orario pubblicato dopo il giorno che sta simulando.

**Come si potrebbe verificare.** Ogni CSV statico porta la colonna `archivio`: se
due tabelle del documento venissero da orari diversi, si vedrebbe leggendo i
file. E `python scripts/materializza_transfers.py --archivio 2026-08-27`
restituisce 8.300 fermate invece di 8.301, che e' la dimostrazione che il
parametro conta.

---

### 74. Committare prima di mutare

**Decisione.** Prima di eseguire una mutazione per collaudare un test, il lavoro in
corso va committato.

**Motivo.** La ricetta usata per verificare che un test copra cio' che dichiara e'
questa: si altera il codice, si esegue la suite, si conta quanti test diventano
rossi, e si ripristina con `git checkout -- <file>`. L'ultimo passo **cancella
tutto cio' che nel file non e' ancora committato**, non solo la mutazione. E'
successo due volte nella stessa giornata: la prima ha portato via l'invariante
appena aggiunto a `ModelloBayesiano`, la seconda l'intero `--senza-scrittura` del
consolidamento.

**Perche' non se ne accorge subito.** In entrambi i casi la suite e' tornata verde
o quasi, perche' cio' che era stato cancellato era **l'aggiunta**, non una rottura:
il codice tornava a uno stato funzionante e precedente. Il primo caso e' emerso
solo perche' un test scritto contestualmente e' rimasto e ha cominciato a fallire;
senza quel test la modifica sarebbe sparita in silenzio.

**Alternative considerate.** Ripristinare con una copia del file invece che con
`git checkout`: funziona, ma aggiunge un passo da ricordare proprio quando si sta
pensando ad altro. Mutare su una copia del repository: costa piu' di quanto valga
per una mutazione di una riga.

**Come si potrebbe verificare.** `git status` prima di ogni mutazione: se elenca
file modificati, il ripristino ne portera' via le modifiche.

### 75. Un collector che funziona non garantisce dati

**Constatazione.** Dalla mezzanotte del 10 settembre 2026 il feed real-time di
Torino restituisce un `FeedMessage` protobuf **vuoto**: quindici byte, il solo
header. Il collector ha continuato a interrogare regolarmente - 1.440 dump il 10,
altri 834 entro le 13:53 dell'11 - e ha scritto su disco 1.440 file identici e
privi di contenuto. L'ultimo dump utile e' delle 23:59 del 9 settembre.

**Perche' nessun controllo se ne e' accorto.** `deploy/stato.sh` guardava il
servizio, non il dato: unit attiva, nessuna interruzione registrata in
`gaps.jsonl`, interrogazioni tutte riuscite, spazio su disco che scende, battito
aggiornato al minuto. Ogni indicatore diceva che andava bene, ed erano tutti veri:
il collector **funzionava**. Cio' che mancava era la domanda successiva, se quello
che arrivava contenesse qualcosa.

Se ne e' accorto per caso un conteggio fatto per un'altra ragione - la quota di
righe conservate dalla deduplica su tutte le giornate - in cui una riga riportava
zero `stop_time_update` su 1.440 dump. Senza quel conteggio il silenzio sarebbe
rimasto invisibile fino a quando qualcuno non avesse provato a usare quei giorni.

**E' lo stesso meccanismo della voce 63.** Li' il ritardo massimo fra le
constatazioni torinesi valeva esattamente zero, e non era un dato ma una
definizione chiusa su se' stessa; qui l'indicatore di salute misurava se stesso
invece del fenomeno. In entrambi i casi il segnale d'allarme e' arrivato da una
statistica di contorno chiesta per altro, ed e' la ragione per cui vanno guardate
anche quando non servono alla domanda.

**Decisione.** `deploy/stato.sh` misura ora la **dimensione mediana** dei dump di
`trip_updates` delle ultime due giornate, e avvisa se scende sotto i cento byte o
se piu' di un quarto dei dump sono vuoti. La mediana e non la media, perche' di
notte qualche dump vuoto e' normale anche su un feed sano; cento byte e non una
soglia tarata, perche' fra un protobuf vuoto - quindici byte - e il piu' piccolo
dump utile osservato in tre settimane - trentaquattromila - ci sono tre ordini di
grandezza e nessuna zona grigia.

**Che cosa questo non tocca.** La finestra di stima si ferma al 9 settembre, quindi
nessun risultato del progetto usa quelle giornate. Toccherebbe pero' chiunque
rieseguisse senza `--fino-a`, ed e' un'altra ragione per cui quella colonna esiste
(voce 73). Roma non ne e' mai stata affetta: la mediana dei suoi dump sta fra
431.149 e 881.271 byte in tutte e diciassette le giornate.

**La causa, diagnosticata l'11 settembre.** Non e' nostra e non e' un endpoint
spostato. Interrogando a mano i due feed di GTT:

- `trip_update.aspx` risponde **HTTP 200** con un protobuf **valido**, header
  `gtfs_realtime_version 2.0`, timestamp aggiornato **al secondo**, e **zero
  entita'**;
- `vehicle_position.aspx`, allo stesso istante, risponde con **354 entita'**, cioe'
  354 veicoli tracciati e in circolazione;
- il GTFS statico si scarica regolarmente, 22,7 MB.

Il produttore quindi pubblica attivamente, sa che ora e', e **ha smesso di produrre
previsioni di orario** pur continuando a sapere dove sono i mezzi. E' un guasto nel
loro sottosistema di predizione, non nella rete, non nel nostro collector, non
nell'URL. Un 404 travestito o un endpoint spostato avrebbero avuto un'altra firma,
ed e' per distinguerli che la diagnosi guarda codice, tipo e **contenuto** invece
che solo la riuscita della richiesta.

**Il residuo del 9 settembre non e' un'ombra.** Quella giornata aveva 250 dump
vuoti su 1.433, e la domanda era se il silenzio fosse cominciato prima di
mezzanotte, il che avrebbe reso cieche le ultime ore di una giornata che sta
**dentro** la finestra di stima e fra quelle di verifica del backtest. La
distribuzione oraria dice di no: i 250 vuoti stanno tutti fra le 00:00 e le 05:59,
quando il servizio torinese non circola, e dalle 06:00 alle 23:59 i vuoti sono
**zero**. Il silenzio comincia esattamente alla mezzanotte del 10.

**Come si potrebbe verificare.** `./deploy/stato.sh` sulla VM lo dice a ogni
esecuzione. La prova che il controllo funzioni e' che, appena installato, ha
segnalato che il silenzio era **ancora in corso** - cosa che nessuno sapeva.

### 76. Le osservazioni per passaggio misurano noi, non il produttore

**Constatazione.** Il numero di valori distinti che conserviamo per ciascun
passaggio dipende fortemente da **quanto spesso interroghiamo**: correlazione di
Pearson **+0,847 (p < 0,0001)** su Roma e **+0,530 (p = 0,042)** su Torino, fra i
dump raccolti in una giornata e i valori per passaggio di quella giornata. Non e'
una cautela metodologica, e' un fatto sul dato: quella grandezza descrive il nostro
campionamento almeno quanto il comportamento di chi pubblica.

Il motivo, ovvio a posteriori, e' che ogni interrogazione e' un'occasione di vedere
una previsione cambiata. Chi interroga ogni minuto ne coglie piu' di chi interroga
ogni mezz'ora, **a parita' di produttore**.

**Che cosa invece non dipende dalla cadenza.** La quota di righe che la deduplica
conserva - il rapporto fra righe scritte e `stop_time_update` letti - non mostra
correlazione significativa con la densita': +0,376 (p = 0,151) su Roma, +0,490
(p = 0,064) su Torino. E' un rapporto fra due grandezze che crescono insieme, e
questo lo rende confrontabile fra citta' interrogate diversamente.

**La conseguenza sul confronto fra le due citta'.** La voce 59 elenca le
osservazioni per passaggio fra le misure su cui i due produttori differiscono. Il
confronto resta valido, ma andava rifatto a cadenza pari, perche' Roma aveva avuto
una fase iniziale a cadenza ridotta - 1.244 dump al giorno in media contro i 1.394
di Torino - che **abbassava** il suo numero. Rifatto sulle sole giornate a cadenza
piena, il divario non si riduce: **si allarga**, da 2,43 a 2,85 volte.

| | tutte le giornate piene | solo cadenza piena (>= 1.400 dump) |
| --- | ---: | ---: |
| Roma | 17,6725 +/- 3,6034 (16 giornate) | **20,1924 +/- 0,9716** (9 giornate) |
| Torino | 7,0381 +/- 0,3237 (15 giornate) | **7,0805 +/- 0,2896** (14 giornate) |
| divario fra le medie | 2,51x | **2,85x** |

Torino non si muove perche' era gia' a cadenza piena quasi ovunque; Roma sale
perche' le sue giornate lente pesavano verso il basso. La conclusione della voce
59 - due filosofie di pubblicazione diverse - ne esce rafforzata, e con un numero
che ora misura loro invece di noi.

*Una correzione a questa stessa voce.* La prima stesura riportava 20,28 e 7,07,
che sono i **rapporti aggregati** - righe totali su passaggi totali - e non hanno
deviazione. Le medie fra giornate valgono 20,19 e 7,08, e sono quelle che il
documento usa, perche' un risultato senza la sua variabilita' e' un risultato da
rifare. La differenza fra le due letture e' di un decimo di punto e non sposta
alcuna conclusione, ma le due forme non si scambiano.

**Decisione.** Le osservazioni per passaggio si riportano **solo su giornate a
cadenza piena**, dichiarando la soglia, e accanto alla misura si dichiara la
dipendenza dalla cadenza. La quota conservata si puo' riportare su tutte le
giornate piene.

**Come si potrebbe verificare.** `results/consolidamento.csv` porta `dump_letti`
accanto a ogni misura: la correlazione si ricalcola in una riga. Se un giorno la
cadenza cambiasse, si vedrebbe da quella colonna invece di restare dentro la media.
