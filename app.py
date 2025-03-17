from flask import Flask, render_template, request, redirect, url_for
import traceback

app = Flask(__name__)
app.secret_key = "mysecretkey"

# Variable globale pour stocker l'état du jeu
game = None

class Game:
    def __init__(self, num_players):
        self.num_players = num_players
        self.grid_size = 3 if num_players == 2 else 5
        # Grille d'affichage : chaque case contiendra le nom de l'équipe, "yellow" ou vide
        self.grid = [['' for _ in range(self.grid_size)] for _ in range(self.grid_size)]
        # Grille de gestion interne pour le défi, avec les informations par case
        self.cells = [
            [{"owner": None, "first_solver": None, "failed": set(), "yellow": False} for _ in range(self.grid_size)]
            for _ in range(self.grid_size)
        ]
        if num_players == 2:
            self.turn_order = [
                {'team': 'red'},
                {'team': 'blue'}
            ]
            self.win_count = 3
        else:
            # Pour le mode 4 joueurs, on travaille en phases simultanées :
            # les deux joueurs ayant le rôle "p1" jouent en même temps, puis ceux en "p2".
            self.turn_order = [
                {'team': 'red', 'role': 'p1'},
                {'team': 'blue', 'role': 'p1'},
                {'team': 'red', 'role': 'p2'},
                {'team': 'blue', 'role': 'p2'}
            ]
            self.win_count = 5
            # Dictionnaire pour stocker les coups en attente pour la phase en cours
            self.pending_moves = {}
            # Définir la phase actuelle (p1 ou p2)
            self.current_phase = "p1"
        self.current_turn = 0
        self.winner = None

    def current_player(self):
        # Pour le mode 2 joueurs, renvoie le joueur courant
        return self.turn_order[self.current_turn % len(self.turn_order)]

    def attempt_challenge(self, row, col, player, code):
        cell = self.cells[row][col]
        # Si la case est bloquée (jaune), aucune tentative n'est possible.
        if cell["yellow"]:
            return False, "La case est bloquée (jaune), aucune tentative possible."
        # Si la case est déjà marquée, on vérifie que le joueur ne l'a pas déjà remportée en premier,
        # et qu'il n'a pas déjà échoué sur cette case.
        if cell["owner"] is not None:
            if cell["first_solver"] == player["team"]:
                return False, "Vous ne pouvez pas réessayer sur une case que vous avez remportée en premier."
            if player["team"] in cell["failed"]:
                return False, "Vous avez déjà tenté de capturer cette case et échoué."
        # Évaluation du code soumis par le joueur
        try:
            local_env = {}
            exec(code, {}, local_env)
            if "addition" not in local_env or not callable(local_env["addition"]):
                raise Exception("La fonction addition n'est pas définie correctement.")
            func = local_env["addition"]
            # Tests simples de vérification
            if func(2, 3) != 5 or func(10, 20) != 30:
                raise Exception("La fonction addition ne retourne pas les résultats attendus.")
        except Exception as e:
            # En cas d'erreur, si la case était vide on la bloque en jaune,
            # sinon on enregistre l'échec pour l'équipe qui a tenté.
            if cell["owner"] is None:
                cell["yellow"] = True
                self.grid[row][col] = "yellow"
            else:
                cell["failed"].add(player["team"])
            return False, f"Erreur : {str(e)}"
        # Si la solution est correcte, la case est marquée (ou reprise) par l'équipe
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

    def check_tie(self):
        """
        Vérifie si aucune séquence gagnante n'est possible (c'est-à-dire si,
        dans toutes les lignes, colonnes et diagonales, il existe un segment
        de longueur 'win_count' contenant une case bloquée en jaune).
        """
        n = self.grid_size
        k = self.win_count

        def segment_available(positions):
            for (i, j) in positions:
                if self.cells[i][j]["yellow"]:
                    return False
            return True

        # Lignes
        for i in range(n):
            for j in range(n - k + 1):
                positions = [(i, x) for x in range(j, j + k)]
                if segment_available(positions):
                    return False

        # Colonnes
        for j in range(n):
            for i in range(n - k + 1):
                positions = [(x, j) for x in range(i, i + k)]
                if segment_available(positions):
                    return False

        # Diagonales (haut-gauche vers bas-droit)
        for i in range(n - k + 1):
            for j in range(n - k + 1):
                positions = [(i + d, j + d) for d in range(k)]
                if segment_available(positions):
                    return False

        # Diagonales (haut-droit vers bas-gauche)
        for i in range(n - k + 1):
            for j in range(k - 1, n):
                positions = [(i + d, j - d) for d in range(k)]
                if segment_available(positions):
                    return False

        return True

    def update_winner(self):
        # Vérification de la victoire pour chaque équipe
        for player in self.turn_order:
            team = player["team"]
            if self.check_win(team):
                self.winner = team
                return
        # Si aucune équipe n'a gagné et qu'aucun segment jouable ne reste, c'est une égalité
        if self.check_tie():
            self.winner = "Tie"

@app.route('/', methods=["GET", "POST"])
def home():
    global game
    if request.method == "POST":
        num_players = int(request.form.get("num_players"))
        if num_players not in [2, 4]:
            error = "Nombre de joueurs invalide. Veuillez choisir 2 ou 4."
            return render_template("home.html", error=error)
        game = Game(num_players)
        return redirect(url_for("grid"))
    return render_template("home.html")

@app.route('/grid')
def grid():
    global game
    if not game:
        return redirect(url_for("home"))
    # Pour le mode 4 joueurs, on transmet la phase courante afin d'afficher le message adéquat
    if game.num_players == 4:
        return render_template("grid.html",
                               grid=game.grid,
                               grid_size=game.grid_size,
                               current_phase=game.current_phase,
                               winner=game.winner,
                               turn=game.current_turn)
    else:
        current_player = game.current_player() if not game.winner else None
        return render_template("grid.html",
                               grid=game.grid,
                               grid_size=game.grid_size,
                               current_player=current_player,
                               winner=game.winner,
                               turn=game.current_turn)

@app.route('/move/<int:row>/<int:col>')
def move(row, col):
    global game
    if not game or game.winner:
        return redirect(url_for("grid"))
    # Redirige vers la page du défi
    return redirect(url_for("challenge", row=row, col=col))

@app.route('/challenge/<int:row>/<int:col>', methods=["GET"])
def challenge(row, col):
    global game
    if not game or game.winner:
        return redirect(url_for("grid"))
    cell = game.cells[row][col]
    if cell["yellow"]:
        return redirect(url_for("grid"))
    challenge_text = ("Écrire une fonction 'addition' qui prend deux entiers et renvoie leur somme. "
                      "Exemple : addition(2, 3) doit renvoyer 5.")
    return render_template("challenge.html", row=row, col=col, challenge_text=challenge_text)

@app.route('/submit_challenge/<int:row>/<int:col>', methods=["POST"])
def submit_challenge(row, col):
    global game
    if not game or game.winner:
        return redirect(url_for("grid"))
    code = request.form.get("code")
    # Traitement en fonction du mode de jeu
    if game.num_players == 4:
        # Pour le mode 4 joueurs, on attend la soumission simultanée des deux joueurs de la phase en cours.
        current_player = None
        # Identifier le joueur qui soumet et vérifier que son rôle correspond à la phase en cours
        for player in game.turn_order:
            if player.get("role") == game.current_phase:
                # On se base sur la couleur pour différencier les équipes (red et blue)
                # On ne peut pas déterminer précisément le "current_player" ici car les deux joueurs jouent simultanément.
                # On utilisera directement la clé de l'équipe pour le stockage.
                if player["team"] in game.pending_moves:
                    continue
                else:
                    current_player = player
                    break

        # Ici, on suppose que le joueur qui soumet a bien le rôle correspondant à la phase courante.
        # Stockage du coup en attente pour l'équipe correspondante.
        # On utilise la couleur extraite depuis la soumission du formulaire.
        # Pour simplifier, on suppose que l'équipe du joueur est celle indiquée dans la route de soumission.
        # Dans une application réelle, l'authentification permettrait de déterminer cela de manière fiable.
        # Nous récupérons la couleur depuis le paramètre "code" via la session ou autre mécanisme.
        # Ici, nous utiliserons un simple mécanisme de simulation en utilisant une variable temporaire.
        # Pour cet exemple, nous allons supposer que le joueur est identifié par un paramètre "team" dans le formulaire.
        team = request.form.get("team")
        if not team:
            return redirect(url_for("grid"))
        game.pending_moves[team] = {"row": row, "col": col, "code": code}
        # Si les deux équipes ont soumis leur coup pour la phase en cours, on les traite simultanément.
        if len(game.pending_moves) == 2:
            for team_key, move in game.pending_moves.items():
                dummy_player = {"team": team_key, "role": game.current_phase}
                success, message = game.attempt_challenge(move["row"], move["col"], dummy_player, move["code"])
                # Vous pouvez enregistrer ou afficher le message ici si nécessaire.
            game.pending_moves.clear()
            game.update_winner()
            # Changement de phase :
            if game.current_phase == "p1":
                game.current_phase = "p2"
            else:
                game.current_phase = "p1"
                # Incrémentation du tour complet (les deux phases ayant été jouées)
                game.current_turn += 2
        return redirect(url_for("grid"))
    else:
        # Mode 2 joueurs (séquentiel)
        current_player = game.current_player()
        success, message = game.attempt_challenge(row, col, current_player, code)
        if success:
            game.current_turn += 1
            game.update_winner()
        return redirect(url_for("grid"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)

