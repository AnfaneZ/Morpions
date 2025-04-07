const socket = io();

document.querySelectorAll(".cell").forEach(cell => {
    cell.addEventListener("click", function () {
        const row = this.dataset.row;
        const col = this.dataset.col;

        if (this.textContent !== "") {
            alert("Cette case est déjà prise !");
            return;
        }

        // Affichage du défi avant d'envoyer au serveur
        const code = prompt("Défi : Écrire une fonction 'addition' qui prend deux nombres et retourne leur somme. Exemple : addition(2,3) doit renvoyer 5. \n\nÉcrivez votre fonction ici :");

        if (code) {
            socket.emit("mark_case", { row, col, team: "red", code: code });
        }
    });
});

socket.on("update_grid", data => {
    document.querySelectorAll(".cell").forEach(cell => {
        const row = cell.dataset.row;
        const col = cell.dataset.col;
        cell.textContent = data.grid[row][col];

        if (data.grid[row][col] === "red") {
            cell.classList.add("red");
        } else if (data.grid[row][col] === "blue") {
            cell.classList.add("blue");
        } else if (data.grid[row][col] === "yellow") {
            cell.classList.add("yellow");
        }
    });
});
