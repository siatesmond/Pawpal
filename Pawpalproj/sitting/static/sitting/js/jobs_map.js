// Find jobs map: the sitter's service area plus one pin per open request.
// Leaflet draws the map and OneMap supplies the map pictures (free, no key).
// The page sends the data with |json_script as "map-centre" and "map-pins".

const centre = JSON.parse(document.getElementById("map-centre").textContent);
const pins = JSON.parse(document.getElementById("map-pins").textContent);

// Singapore only: OneMap has no map pictures outside these corners
const singapore = L.latLngBounds([1.144, 103.535], [1.494, 104.502]);

// map centred on the sitter's service area
const map = L.map("jobs-map", { maxBounds: singapore, minZoom: 11, maxZoom: 19 })
  .setView([centre.lat, centre.lng], 12);

L.tileLayer("https://www.onemap.gov.sg/maps/tiles/Default/{z}/{x}/{y}.png", {
  minZoom: 11,
  maxZoom: 19,
  bounds: singapore,
  attribution: '<a href="https://www.onemap.gov.sg/" target="_blank">OneMap</a> &copy; contributors | <a href="https://www.sla.gov.sg/" target="_blank">Singapore Land Authority</a>',
}).addTo(map);

// green circle = the distance filter around the sitter
L.circle([centre.lat, centre.lng], {
  radius: centre.radius_km * 1000,
  color: "#55644A",
  fillColor: "#55644A",
  fillOpacity: 0.12,
  weight: 1,
}).addTo(map);

// the sitter's own location: a green dot with a "You" label
L.circleMarker([centre.lat, centre.lng], {
  radius: 9,
  color: "#ffffff",
  weight: 3,
  fillColor: "#55644A",
  fillOpacity: 1,
})
  .addTo(map)
  .bindTooltip("You · " + centre.label, { permanent: true, direction: "bottom", offset: [0, 8] });

// turn < > & " into safe text, so names typed by users cannot inject HTML
function safe(text) {
  const box = document.createElement("span");
  box.textContent = text;
  return box.innerHTML;
}

// one pin per request; click it to see the details
for (const pin of pins) {
  let popupText = "<strong>" + safe(pin.title) + "</strong><br>" + safe(pin.pets) + "<br>SGD " + safe(pin.price);
  if (pin.distance !== null) {
    popupText += " · " + pin.distance + " km";
  }
  L.marker([pin.lat, pin.lng]).addTo(map).bindPopup(popupText);
}
