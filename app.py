from flask import Flask, render_template, request, redirect, url_for, flash, session
import os
import uuid
import json
import traceback
import ollama  # client Ollama

ollama_client = ollama.Client()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change_this_secret")

games = {}

class Game:
    def __init__(self, num_players):
        self.num_players = num_players
        self.grid_size = 3 if num_players == 2 else 5
        self.grid = [['' for _ in range(self.grid_size)] for _ in range(self.grid_size)]
        self.cells = [[{"owner":None,"first_solver":None,"failed":set(),"yellow":False,"challenge":None} for _ in range(self.grid_size)] for _ in range(self.grid_size)]
        self.win_count = 3 if num_players == 2 else 5
        self.players=[]
        self.current_turn=0
        self.winner=None

    def add_player(self,name,team,role=None):
        for p in self.players:
            if p["name"]==name or (p.get("team")==team and (role is None or p.get("role")==role)):
                return None
        player={"name":name,"team":team}
        if role: player["role"]=role
        self.players.append(player)
        return player

    def current_player(self):
        return None if not self.players else self.players[self.current_turn%len(self.players)]

    def is_player_turn(self, player_name):
        cp = self.current_player()
        return cp and cp.get("name") == player_name

    def generate_challenge(self,row,col):
        prompt=("Génère une question de programmation en Python au format JSON avec ces clés:\n"
                "- description: énoncé du problème,\n"
                "- function_name: def nom_de_la_fonction\n"
                "- précisions: le problème doit se baser sur des listes de nombre, et des concepts algorithmique,\n"
                "- tests: liste d'objets {input: liste d'arguments, output: résultat attendu}.\n"
                "Fournis uniquement l'objet JSON.")
        resp=ollama_client.generate(model='llama3.2:3b',prompt=prompt,options={"stream":False})
        raw=getattr(resp,'response',None) or resp.get('response') or resp.get('text')
        if not raw and resp.get('choices'): raw=resp['choices'][0].get('text') or (resp['choices'][0].get('message') or {}).get('content')
        raw=(raw or '').strip('` \n')
        if raw.startswith('json'): raw=raw[len('json'):].strip()
        try:
            data=json.loads(raw)
        except Exception:
            traceback.print_exc()
            # extraire portion JSON brute
            start=raw.find('{')
            end=raw.rfind('}')
            if start!=-1 and end!=-1:
                try:
                    data=json.loads(raw[start:end+1])
                except Exception:
                    raise ValueError(f"Échec parse JSON, raw: {raw}")
            else:
                raise ValueError(f"Pas de JSON détecté, raw: {raw}")
        self.cells[row][col]["challenge"]=data
        return data

    def attempt_challenge(self,row,col,player,code):
        cell=self.cells[row][col]
        if player["team"] in cell["failed"]: return False,"Vous avez déjà tenté et échoué."
        challenge=cell.get("challenge")
        if not challenge: return False,"Aucun défi disponible."
        verify_prompt=("Vérifie en Python si le code résout le défi donné. Répond uniquement JSON avec { \"result\": \"OK\" ou \"KO\", \"errors\": [...] }\n"
                       f"Défi: {json.dumps(challenge)}\nCode du joueur:\n```python\n{code}\n```\n")
        resp=ollama_client.generate(model='llama3.2:3b',prompt=verify_prompt,options={"stream":False})
        raw=getattr(resp,'response',None) or resp.get('response') or resp.get('text')
        if not raw and resp.get('choices'): raw=resp['choices'][0].get('text')
        raw=(raw or '').strip('` \n')
        # extraire JSON substring
        jstart=raw.find('{')
        jend=raw.rfind('}')
        json_part=raw[jstart:jend+1] if jstart!=-1 and jend!=-1 else raw
        try:
            result=json.loads(json_part)
        except Exception:
            cell["failed"].add(player["team"])
            cell["yellow"]=True
            self.grid[row][col]="yellow"
            return False,f"Réponse IA invalide: {raw}"
        if result.get("result")!="OK":
            cell["failed"].add(player["team"])
            cell["yellow"]=True
            self.grid[row][col]="yellow"
            return False,"Wrong Answer (IA)"
        if cell.get("owner") is None: cell["first_solver"]=player["team"]
        cell["owner"]=player["team"]
        self.grid[row][col]=player["team"]
        return True,"Bonne réponse."

    def check_win(self):
        lines = []
        lines.extend(self.grid)  # lignes horizontales
        lines.extend([[self.grid[r][c] for r in range(self.grid_size)] for c in range(self.grid_size)])  # colonnes verticales
        lines.append([self.grid[i][i] for i in range(self.grid_size)])  # diagonale principale
        lines.append([self.grid[i][self.grid_size-1-i] for i in range(self.grid_size)])  # diagonale secondaire

        for line in lines:
            if line[0] and all(cell == line[0] for cell in line):
                return line[0]
        return None


    def check_draw(self):
    # Si toutes les cellules de la grille sont occupées (non vides) et pas de gagnant
        for row in self.grid:
            for cell in row:
                if cell == '':
                    return False
        # Toutes les cases sont remplies
        if not self.check_win():
            return True
        return False


    def update_winner(self):
        w = self.check_win()
        if w:
            self.winner = w
        elif self.check_draw():
            self.winner = "draw"  # ou None, ou un autre marqueur pour égalité
        else:
            self.winner=None


# routes inchangés

@app.route('/', methods=["GET", "POST"])
def home():
    if request.method == "POST":
        try:
            np = int(request.form['num_players'])
        except:
            flash("Nombre invalide")
            return render_template("home.html")
        if np not in [2, 4]:
            flash("Choix 2 ou 4")
            return render_template("home.html")
        name = request.form['host_name']
        if not name:
            flash("Entrez nom")
            return render_template("home.html")
        gid = str(uuid.uuid4())
        g = Game(np)
        g.add_player(name, 'red', 'p1' if np == 4 else None)
        session['player_name'] = name
        games[gid] = g
        return redirect(url_for('waiting', game_id=gid))
    return render_template("home.html")

@app.route('/invite/<game_id>')
def invite(game_id):
    if game_id not in games:
        flash("No game")
        return redirect(url_for('home'))
    join_url = request.url_root + f"join/{game_id}"
    return render_template("invite.html", join_url=join_url)

@app.route('/join/<game_id>', methods=["GET", "POST"])
def join(game_id):
    if game_id not in games:
        flash("No game")
        return redirect(url_for('home'))
    g = games[game_id]
    if request.method == 'POST':
        p = g.add_player(request.form['name'], request.form['team'], request.form.get('role'))
        if not p:
            flash("Nom/équipe pris")
            return redirect(url_for('join', game_id=game_id))
        session['player_name'] = request.form['name']
        return redirect(url_for('waiting', game_id=game_id))
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

@app.route('/grid/<game_id>', endpoint='grid')
def grid(game_id):
    g = games.get(game_id)
    if not g or len(g.players) < g.num_players:
        return redirect(url_for('waiting', game_id=game_id))
    # Vérifie s'il y a un gagnant
    if g.winner == "draw":
        flash("Match nul ! La grille est remplie sans vainqueur.")
    elif g.winner:
        flash(f"Le gagnant est l'équipe {g.winner} !")
    player_name = session.get('player_name')
    return render_template(
        "grid.html",
        grid=g.grid,
        grid_size=g.grid_size,
        cells=g.cells,
        current_player=g.current_player(),
        winner=g.winner,
        turn=g.current_turn,
        game_id=game_id,
        player_name=player_name
    )

@app.route('/move/<game_id>/<int:row>/<int:col>')
def move(game_id, row, col):
    g = games.get(game_id)
    player_name = session.get('player_name')
    if not g or g.winner:
        flash("La partie est terminée.")
        return redirect(url_for('grid', game_id=game_id))
    if not g.is_player_turn(player_name):
        flash("Ce n'est pas à vous de jouer.")
        return redirect(url_for('grid', game_id=game_id))
    return redirect(url_for('challenge', game_id=game_id, row=row, col=col))

@app.route('/challenge/<game_id>/<int:row>/<int:col>')
def challenge(game_id, row, col):
    g = games[game_id]
    player_name = session.get('player_name')
    if not g.is_player_turn(player_name):
        flash("Ce n'est pas à vous de jouer.")
        return redirect(url_for('grid', game_id=game_id))

    cell = g.cells[row][col]
    if cell['challenge'] is None:
        # Affiche la page de chargement
        return render_template("loading.html", game_id=game_id, row=row, col=col)
    
    return render_template(
        "challenge.html",
        challenge_text=cell['challenge']['description'],
        row=row, col=col, game_id=game_id
    )

@app.route('/challenge_ready/<game_id>/<int:row>/<int:col>')
def challenge_ready(game_id, row, col):
    g = games[game_id]
    player_name = session.get('player_name')
    if not g.is_player_turn(player_name):
        flash("Ce n'est pas à vous de jouer.")
        return redirect(url_for('grid', game_id=game_id))

    cell = g.cells[row][col]
    if cell['challenge'] is None:
        try:
            cell['challenge'] = g.generate_challenge(row, col)
        except Exception as e:
            flash("Erreur lors de la génération du défi.")
            return redirect(url_for('grid', game_id=game_id))

    return redirect(url_for('challenge', game_id=game_id, row=row, col=col))


@app.route('/submit_challenge/<game_id>/<int:row>/<int:col>', methods=["POST"])
def submit_challenge(game_id, row, col):
    g = games[game_id]
    player_name = session.get('player_name')
    if g.winner:
        flash("La partie est terminée.")
        return redirect(url_for('grid', game_id=game_id))
    if not g.is_player_turn(player_name):
        flash("Ce n'est pas à vous de jouer.")
        return redirect(url_for('grid', game_id=game_id))

    code = request.form['code']
    player = g.current_player()
    success, msg = g.attempt_challenge(row, col, player, code)
    flash(msg)

    # Toujours passer au joueur suivant
    g.current_turn += 1
    g.update_winner()

    return redirect(url_for('grid', game_id=game_id))



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
