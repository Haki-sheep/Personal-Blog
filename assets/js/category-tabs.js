document.querySelectorAll(".subcategory-switcher").forEach(function (switcher) {
    var tabs = switcher.querySelectorAll(".subcategory-tab");
    var panels = switcher.querySelectorAll(".subcategory-panel");

    tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
            tabs.forEach(function (item) {
                item.classList.remove("is-active");
                item.setAttribute("aria-selected", "false");
            });
            panels.forEach(function (panel) {
                panel.classList.remove("is-active");
            });

            tab.classList.add("is-active");
            tab.setAttribute("aria-selected", "true");

            var target = switcher.querySelector("#" + tab.dataset.panel);
            if (target) {
                target.classList.add("is-active");
            }
        });
    });
});
