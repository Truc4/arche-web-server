// Served as application/javascript by the Arche server.
const el = document.getElementById("clock");
function tick() {
  el.textContent = "client time: " + new Date().toLocaleTimeString();
}
tick();
setInterval(tick, 1000);
