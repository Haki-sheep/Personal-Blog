document.querySelectorAll(".menu-group-toggle").forEach(function (btn) {
    btn.addEventListener("click", function () {
        var group = btn.closest(".menu-group");
        var expanded = group.classList.toggle("is-expanded");
        btn.setAttribute("aria-expanded", expanded ? "true" : "false");
    });
});

document.querySelectorAll(".menu-group.is-active").forEach(function (group) {
    group.classList.add("is-expanded");
    var btn = group.querySelector(".menu-group-toggle");
    if (btn) {
        btn.setAttribute("aria-expanded", "true");
    }
});
