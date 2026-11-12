// Photo preview for every photo upload in Pawpal (loaded once by the base templates).
//
// How to use it in a template: give the file input an id, e.g. id="id_photo",
// and put an element with the same id plus "-preview" where the photo should show:
//   <img id="id_photo-preview" hidden>      -> the chosen photo appears in it
//   <div id="id_photo-preview">▧</div>      -> the box is swapped for the chosen photo
// For <input multiple>, the element is filled with a small picture of every photo.

document.addEventListener("change", function (event) {
  const input = event.target;
  if (input.type !== "file" || !input.id) {
    return;
  }

  const preview = document.getElementById(input.id + "-preview");
  if (!preview) {
    return;
  }

  // only pictures can be previewed (an ID document can be a PDF)
  const photos = [];
  for (const file of input.files) {
    if (file.type.startsWith("image/")) {
      photos.push(file);
    }
  }

  // several photos: show them side by side
  if (input.multiple) {
    preview.innerHTML = "";
    for (const photo of photos) {
      const img = document.createElement("img");
      img.src = URL.createObjectURL(photo);
      img.alt = "Chosen photo";
      preview.appendChild(img);
    }
    preview.hidden = photos.length === 0;
    return;
  }

  if (photos.length === 0) {
    return;
  }

  const photoUrl = URL.createObjectURL(photos[0]);
  if (preview.tagName === "IMG") {
    preview.src = photoUrl;
    preview.hidden = false;
  } else {
    // a placeholder box: replace it with a picture that keeps the same id and look
    const img = document.createElement("img");
    img.id = preview.id;
    img.className = preview.className.replace("pet-avatar-empty", "").trim();
    img.src = photoUrl;
    img.alt = "Chosen photo";
    preview.replaceWith(img);
  }
});
