from flask import Flask, render_template, request, redirect, url_for, flash, session
import uuid
import traceback

app = Flask(__name__)
app.secret_key = "mysecretkey"


# Dictionnaire global pour stocker les parties actives (clé: game_id)
games = {}

class Game:
    def __init__(self, num_players):
        self.num_players = num_players
        self.grid_size = 3 if num_players == 2 else 5
        # Grille d'affichage
        self.grid = [['' for _ in range(self.grid_size)] for _ in range(self.grid_size)]
        # Grille de gestion interne pour les défis
        self.cells = [
            [{"owner": None, "first_solver": None, "failed": set(), "yellow": False} for _ in range(self.grid_size)]
            for _ in range(self.grid_size)
        ]
        if num_players == 2:
            self.roles = [{'team': 'red'}, {'team': 'blue'}]
            self.win_count = 3
        else:
            self.roles = [
                {'team': 'red', 'role': 'p1'},
                {'team': 'blue', 'role': 'p1'},
                {'team': 'red', 'role': 'p2'},
                {'team': 'blue', 'role': 'p2'}
            ]
            self.win_count = 5
            self.pending_moves = {}
        self.players = []
        self.current_turn = 0
        self.winner = None

    def add_player(self, name, team, role=None):
        # Empêche les doublons
        for p in self.players:
            if p["name"] == name:
                return None  # nom déjà pris

            if self.num_players == 2 and p["team"] == team:
                return None  # équipe déjà prise en 1v1

            if self.num_players == 4 and p["team"] == team and p.get("role") == role:
                return None  # équipe + rôle déjà pris

        player = {"name": name, "team": team}
        if role:
            player["role"] = role
        self.players.append(player)
        return player

    def assign_turn_order(self):
        self.turn_order = []

        if self.num_players == 2:
            for team in ['red', 'blue']:
                for player in self.players:
                    if player['team'] == team:
                        self.turn_order.append(player)
        else:
            order = [
                {'team': 'red', 'role': 'p1'},
                {'team': 'blue', 'role': 'p1'},
                {'team': 'red', 'role': 'p2'},
                {'team': 'blue', 'role': 'p2'}
            ]
            for expected in order:
                for player in self.players:
                    if player['team'] == expected['team'] and player.get('role') == expected['role']:
                        self.turn_order.append(player)

    
    def current_player(self):
        if not self.turn_order:
            return None
        return self.turn_order[self.current_turn % len(self.turn_order)]


    def attempt_challenge(self, row, col, player, code):
        cell = self.cells[row][col]

        # Si le joueur a déjà tenté sur cette case (jaune ou pas), il ne peut plus la rejouer
        if player["team"] in cell["failed"]:
            return False, "Vous avez déjà tenté de capturer cette case et échoué."

        # Si la case est déjà possédée par le joueur qui l'a capturée en premier, il ne peut pas réessayer
        if cell["owner"] is not None and cell["first_solver"] == player["team"]:
            return False, "Vous ne pouvez pas réessayer sur une case que vous avez remportée en premier."

        try:
            local_env = {}
            exec(code, {}, local_env)
            if "addition" not in local_env or not callable(local_env["addition"]):
                raise Exception("La fonction addition n'est pas définie correctement.")
            func = local_env["addition"]
            # Vérification simple
            if func(2, 3) != 5 or func(10, 20) != 30:
                raise Exception("La fonction addition ne retourne pas les résultats attendus.")
        except Exception:
            # ❌ Tentative échouée : on enregistre l'échec pour cette équipe
            cell["failed"].add(player["team"])
            if cell["owner"] is None:
                cell["yellow"] = True
                self.grid[row][col] = "yellow"
            return False, "Wrong Answer"

        # ✅ Tentative réussie : la case est capturée
        if cell["owner"] is None:
            cell["owner"] = player["team"]
            cell["first_solver"] = player["team"]
        else:
            cell["owner"] = player["team"]

        self.grid[row][col] = cell["owner"]
        return True, "Bonne réponse, case marquée."


    def check_win(self, team):
        n = self.grid_size
        k = self.win_count
        # Vérification des lignes
        for row in range(n):
            count = 0
            for col in range(n):
                if self.grid[row][col] == team:
                    count += 1
                    if count == k:
                        return True
                else:
                    count = 0
        # Vérification des colonnes
        for col in range(n):
            count = 0
            for row in range(n):
                if self.grid[row][col] == team:
                    count += 1
                    if count == k:
                        return True
                else:
                    count = 0
        # Vérification des diagonales (haut-gauche vers bas-droit)
        for row in range(n):
            for col in range(n):
                if self.grid[row][col] == team:
                    count = 0
                    i, j = row, col
                    while i < n and j < n and self.grid[i][j] == team:
                        count += 1
                        i += 1
                        j += 1
                    if count >= k:
                        return True
        # Vérification des diagonales (haut-droit vers bas-gauche)
        for row in range(n):
            for col in range(n):
                if self.grid[row][col] == team:
                    count = 0
                    i, j = row, col
                    while i < n and j >= 0 and self.grid[i][j] == team:
                        count += 1
                        i += 1
                        j -= 1
                    if count >= k:
                        return True
        return False

    def is_full(self):
        """
        Vérifie si toutes les cases sont marquées.
        """
        for row in self.grid:
            for cell in row:
                if cell == '':
                    return False  # Il y a encore des cases vides
        return True  # Toutes les cases sont marquées

    def check_tie(self):
        """
        Vérifie si la grille est pleine et qu'il n'y a plus de possibilité de victoire.
        """
        # La grille doit être pleine et il ne doit pas y avoir de gagnant
        if self.is_full() and self.winner is None:
            # Si la grille est pleine et qu'il n'y a pas de gagnant, c'est une égalité
            return True
        return False

    def update_winner(self):
        for player in self.players:
            team = player["team"]
            if self.check_win(team):
                self.winner = team
                return
        if self.check_tie():
            self.winner = "Tie"

# Route d'accueil pour créer une nouvelle partie (l'hôte saisit son nom et le nombre de joueurs)
@app.route('/', methods=["GET", "POST"])
def home():
    if request.method == "POST":
        try:
            num_players = int(request.form.get("num_players"))
        except:
            flash("Veuillez entrer un nombre valide.")
            return render_template("home.html")
        if num_players not in [2, 4]:
            flash("Nombre de joueurs invalide. Veuillez choisir 2 ou 4.")
            return render_template("home.html")
        host_name = request.form.get("host_name")
        if not host_name:
            flash("Veuillez entrer votre nom.")
            return render_template("home.html")
        game_id = str(uuid.uuid4())
        game = Game(num_players)
        # Ajout automatique de l'hôte à la partie
        team = "red"
        role = "p1" if num_players == 4 else None
        game.add_player(host_name, team, role)
        # Stocker le nom de l'hôte dans la session
        session["player_name"] = host_name
        games[game_id] = game
        flash("Partie créée avec succès. Partagez le lien d'invitation avec vos amis.")
        return redirect(url_for("waiting", game_id=game_id))
    return render_template("home.html")


# Page d'invitation qui affiche le lien à partager
@app.route('/invite/<game_id>')
def invite(game_id):
    if game_id not in games:
        flash("Partie inexistante.")
        return redirect(url_for("home"))
    join_url = request.url_root + "join/" + game_id
    return render_template("invite.html", join_url=join_url, game_id=game_id, num_players=games[game_id].num_players)

@app.route('/join/<game_id>', methods=["GET", "POST"])
def join(game_id):
    if game_id not in games:
        flash("Partie inexistante.")
        return redirect(url_for("home"))
    
    game = games[game_id]

    if request.method == "POST":
        name = request.form.get("name")
        if not name:
            flash("Veuillez entrer votre nom.")
            return redirect(url_for("join", game_id=game_id))
        
        # Empêche les doublons
        for p in game.players:
            if p["name"] == name:
                flash("Ce nom est déjà pris.")
                return redirect(url_for("join", game_id=game_id))
        team = request.form.get("team")
        role = request.form.get("role") if game.num_players == 4 else None

        
        if not team or (game.num_players == 4 and not role):
            flash("Veuillez sélectionner une équipe et un rôle.")
            return redirect(url_for("join", game_id=game_id))
        
        player = game.add_player(name, team, role)
        if not player:
            flash("La partie est déjà complète.")
            return redirect(url_for("home"))

        session["player_name"] = name
        # TOUJOURS rediriger vers la salle d'attente
        return redirect(url_for("waiting", game_id=game_id))

    return render_template("join.html", game_id=game_id)



@app.route('/waiting/<game_id>')
def waiting(game_id):
    if game_id not in games:
        flash("Partie inexistante.")
        return redirect(url_for("home"))

    game = games[game_id]

    if len(game.players) >= game.num_players:
        return redirect(url_for("grid", game_id=game_id))

    return render_template("waiting.html", game=game, game_id=game_id)



# Affichage de la grille (la partie démarre une fois tous les joueurs réunis)
@app.route('/grid/<game_id>')
def grid(game_id):
    if game_id not in games:
        flash("Partie inexistante.")
        return redirect(url_for("home"))
    game = games[game_id]
    if len(game.players) < game.num_players:
        flash("La partie n'a pas encore assez de joueurs.")
        return redirect(url_for("waiting", game_id=game_id))
    if not game.turn_order:
        game.assign_turn_order()
    current_player = game.current_player() if not game.winner else None
    return render_template("grid.html",
                           grid=game.grid,
                           grid_size=game.grid_size,
                           current_player=current_player,
                           winner=game.winner,
                           turn=game.current_turn,
                           game_id=game_id,
                           cells=game.cells,
                           player_name=session.get("player_name"))


# Route pour sélectionner une case (redirection vers le défi)
@app.route('/move/<game_id>/<int:row>/<int:col>')
def move(game_id, row, col):
    if game_id not in games:
        return redirect(url_for("home"))
    game = games[game_id]
    current_player = game.current_player()
    if not current_player or session.get("player_name") != current_player["name"]:
        flash("Ce n'est pas votre tour.")
        return redirect(url_for("grid", game_id=game_id))
    if game.winner:
        return redirect(url_for("grid", game_id=game_id))
    return redirect(url_for("challenge", game_id=game_id, row=row, col=col))


# Page du défi d'algorithmie
@app.route('/challenge/<game_id>/<int:row>/<int:col>', methods=["GET"])
def challenge(game_id, row, col):
    if game_id not in games:
        return redirect(url_for("home"))
    game = games[game_id]
    if game.winner:
        return redirect(url_for("grid", game_id=game_id))
    challenge_text = ("Écrire une fonction 'addition' qui prend deux entiers et renvoie leur somme. "
                      "Exemple : addition(2, 3) doit renvoyer 5.")
    return render_template("challenge.html", row=row, col=col, challenge_text=challenge_text, game_id=game_id)


# Traitement de la soumission du défi
@app.route('/submit_challenge/<game_id>/<int:row>/<int:col>', methods=["POST"])
def submit_challenge(game_id, row, col):
    if game_id not in games:
        return redirect(url_for("home"))
    
    game = games[game_id]
    
    if game.winner:
        return redirect(url_for("grid", game_id=game_id))
    
    code = request.form.get("code")
    current_player = game.current_player()
    
    # Gestion des coups simultanés pour les joueurs 2 en mode 4 joueurs
    if game.num_players == 4 and current_player.get("role") == "p2":
        game.pending_moves[current_player["team"]] = {"row": row, "col": col, "code": code}
        if len(game.pending_moves) == 2:
            for team, move in game.pending_moves.items():
                dummy_player = {"team": team, "role": "p2"}
                success, message = game.attempt_challenge(move["row"], move["col"], dummy_player, move["code"])
            game.pending_moves = {}
            game.current_turn += 2
            game.update_winner()
        flash("Votre réponse a été soumise.")
        return redirect(url_for("grid", game_id=game_id))
    
    else:
        # Vérifie si la réponse est correcte ou incorrecte
        success, message = game.attempt_challenge(row, col, current_player, code)
        
        if success:
            # Si la réponse est correcte, on passe au joueur suivant
            game.current_turn += 1
        else:
            # Si la réponse est incorrecte, on passe également au joueur suivant
            game.current_turn += 1

        # Vérifie la victoire à chaque tour
        game.update_winner()
        
        # Affiche le message, qu'il soit bon ou mauvais
        flash(message)
        return redirect(url_for("grid", game_id=game_id))


import os

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

