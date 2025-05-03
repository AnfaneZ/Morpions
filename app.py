from flask import Flask, render_template, request, redirect, url_for, flash, session
import os
import uuid
import traceback
import json
import ollama                  # client Ollama

ollama_client = ollama.Client()

app = Flask

# --- Exemple d'appel HTTP direct au modèle Ollama avec la librairie requests (optionnel) ---
import requests

def llama_request(prompt: str, model: str = 'llama3.2:3b') -> dict:
    """
    Envoie une requête HTTP POST à l'API Ollama locale pour générer une réponse.
    Nécessite que le daemon Ollama tourne sur le port 11434.
    Retourne le JSON de réponse.
    """
    url = f"http://localhost:11434/models/{model}"
    payload = {"prompt": prompt, "options": {"stream": False}}
    resp = requests.post(url, json=payload)
    resp.raise_for_status()
    return resp.json()

# Exemple d'utilisation :
# result = llama_request("Hello, world!", model='llama3.2:3b')
# data = result.get('choices', [])[0]
# print(data.get('text'))

app = Flask(__name__)
app.secret_key = "mysecretkey"

games = {}  # stocke les parties actives

class Game:
    def __init__(self, num_players):
        self.num_players = num_players
        self.grid_size = 3 if num_players == 2 else 5
        self.grid = [['' for _ in range(self.grid_size)] for _ in range(self.grid_size)]
        self.cells = [
            [{"owner": None, "first_solver": None, "failed": set(), "yellow": False, "challenge": None}
             for _ in range(self.grid_size)]
            for _ in range(self.grid_size)
        ]
        if num_players == 2:
            self.roles = [{'team': 'red'}, {'team': 'blue'}]
            self.win_count = 3
        else:
            self.roles = [
                {'team': 'red', 'role': 'p1'}, {'team': 'blue', 'role': 'p1'},
                {'team': 'red', 'role': 'p2'}, {'team': 'blue', 'role': 'p2'}
            ]
            self.win_count = 5
            self.pending_moves = {}
        self.players = []
        self.current_turn = 0
        self.winner = None

    def add_player(self, name, team, role=None):
        for p in self.players:
            if p["name"] == name or (p.get("team") == team and (role is None or p.get("role") == role)):
                return None
        player = {"name": name, "team": team}
        if role: player["role"] = role
        self.players.append(player)
        return player

    def current_player(self):
        return None if not self.players else self.players[self.current_turn % len(self.players)]

    def generate_challenge(self, row, col):
        prompt = (
            "Génère un défi de programmation en Python au format JSON avec ces clés:"
            "- description: énoncé du problème,"
            "- function_name: nom de la fonction à implémenter,"
            "- tests: liste d'objets {input: liste d'arguments, output: résultat attendu}."
            "Fournis uniquement l'objet JSON."
        )
        # Appel au modèle Ollama
        resp = ollama_client.generate(model='llama3.2:3b', prompt=prompt, options={"stream": False})
        # Extraire le texte JSON de la réponse
        if hasattr(resp, 'response'):
            raw = resp.response
        elif isinstance(resp, dict) and 'response' in resp:
            raw = resp['response']
        elif isinstance(resp, dict) and 'text' in resp:
            raw = resp['text']
        elif isinstance(resp, dict) and 'choices' in resp and resp['choices']:
            choice = resp['choices'][0]
            raw = choice.get('text') or (choice.get('message') or {}).get('content')
        else:
            raise Exception(f"Réponse inattendue d'Ollama: {resp}")
        # Nettoyer les backticks Markdown
        raw = raw.strip()
        if raw.startswith('```') and raw.endswith('```'):
            # retire les ``` ou ```json
            raw = raw.lstrip('`').lstrip('json').rstrip('`').strip()
        # Charger le JSON
        data = json.loads(raw)
        self.cells[row][col]["challenge"] = data
        return data

    def attempt_challenge(self, row, col, player, code):
        cell = self.cells[row][col]
        if player["team"] in cell["failed"]:
            return False, "Vous avez déjà tenté et échoué."
        challenge = cell.get("challenge")
        if not challenge:
            return False, "Aucun défi disponible."
        fname, tests = challenge['function_name'], challenge['tests']
        try:
            local = {}
            exec(code, {}, local)
            fn = local.get(fname)
            if not callable(fn): raise Exception("Fonction manquante.")
            for t in tests:
                if fn(*t['input']) != t['output']:
                    raise Exception(f"Échec sur {t['input']}")
        except Exception as e:
            cell["failed"].add(player["team"])
            cell["yellow"] = True
            self.grid[row][col] = "yellow"
            return False, f"Wrong Answer: {e}"
        cell_owner = cell.get("owner")
        cell["owner"] = player["team"]
        if cell_owner is None:
            cell["first_solver"] = player["team"]
        self.grid[row][col] = player["team"]
        return True, "Bonne réponse."

    # check_win, is_full, check_tie, update_winner inchangés...

@app.route('/', methods=["GET","POST"])
def home():
    if request.method=="POST":
        try:
            np=int(request.form['num_players'])
        except:
            flash("Nombre invalide")
            return render_template("home.html")
        if np not in [2,4]:
            flash("Choix 2 ou 4")
            return render_template("home.html")
        name=request.form['host_name']
        if not name:
            flash("Entrez nom")
            return render_template("home.html")
        gid=str(uuid.uuid4())
        g=Game(np)
        g.add_player(name,'red','p1' if np==4 else None)
        session['player_name']=name
        games[gid]=g
        return redirect(url_for('waiting',game_id=gid))
    return render_template("home.html")

@app.route('/invite/<game_id>')
def invite(game_id):
    if game_id not in games:
        flash("No game")
        return redirect(url_for('home'))
    join_url = request.url_root + f"join/{game_id}"
    return render_template("invite.html", join_url=join_url)

@app.route('/join/<game_id>',methods=["GET","POST"])
def join(game_id):
    if game_id not in games:
        flash("No game")
        return redirect(url_for('home'))
    g=games[game_id]
    if request.method=='POST':
        p=g.add_player(request.form['name'],request.form['team'],request.form.get('role'))
        if not p:
            flash("Nom/équipe pris")
            return redirect(url_for('join',game_id=game_id))
        session['player_name']=request.form['name']
        return redirect(url_for('waiting',game_id=game_id))
    return render_template("join.html", game=g)

@app.route('/waiting/<game_id>')
def waiting(game_id):
    if game_id not in games:
        flash("Partie inexistante.")
        return redirect(url_for('home'))
    g = games[game_id]
    join_url = request.url_root + f"join/{game_id}"
    if len(g.players) >= g.num_players:
        return redirect(url_for('grid', game_id=game_id))
    return render_template('waiting.html', game=g, game_id=game_id, join_url=join_url)

@app.route('/grid/<game_id>')
def grid(game_id):
    g=games.get(game_id)
    if not g or len(g.players)<g.num_players:
        return redirect(url_for('waiting',game_id=game_id))
    return render_template("grid.html", grid=g.grid, grid_size=g.grid_size, cells=g.cells, current_player=g.current_player(), winner=g.winner, turn=g.current_turn, game_id=game_id)

@app.route('/move/<game_id>/<int:row>/<int:col>')
def move(game_id,row,col):
    return redirect(url_for('challenge',game_id=game_id,row=row,col=col))

@app.route('/challenge/<game_id>/<int:row>/<int:col>')
def challenge(game_id,row,col):
    g=games[game_id]
    cell=g.cells[row][col]
    if cell['challenge'] is None:
        cell['challenge']=g.generate_challenge(row,col)
    return render_template("challenge.html", challenge_text=cell['challenge']['description'], row=row, col=col, game_id=game_id)

@app.route('/submit_challenge/<game_id>/<int:row>/<int:col>',methods=["POST"])
def submit_challenge(game_id,row,col):
    g=games[game_id]
    code=request.form['code']
    player=g.current_player()
    success,msg=g.attempt_challenge(row,col,player,code)
    flash(msg)
    if success:
        g.current_turn+=1
        g.update_winner()
    return redirect(url_for('grid',game_id=game_id))

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=True)
