/**
 * SIMP — Landing Page Script
 * Ванильный JS без зависимостей: scroll-reveal, мобильное меню,
 * плавный скролл к якорям, динамический год копирайта.
 */
(function () {
  "use strict";

  var prefersReducedMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)"
  ).matches;

  /* ── Динамический год в футере ─────────────────────────────── */
  document.querySelectorAll("[data-year]").forEach(function (el) {
    el.textContent = String(new Date().getFullYear());
  });

  /* ── Мобильное меню ─────────────────────────────────────────── */
  var navToggle = document.querySelector("[data-nav-toggle]");
  var mobileNav = document.querySelector("[data-mobile-nav]");

  if (navToggle && mobileNav) {
    var closeMenu = function () {
      navToggle.setAttribute("aria-expanded", "false");
      mobileNav.classList.remove("is-open");
      document.body.style.overflow = "";
    };
    var openMenu = function () {
      navToggle.setAttribute("aria-expanded", "true");
      mobileNav.classList.add("is-open");
      document.body.style.overflow = "hidden";
    };

    navToggle.addEventListener("click", function () {
      var expanded = navToggle.getAttribute("aria-expanded") === "true";
      if (expanded) {
        closeMenu();
      } else {
        openMenu();
      }
    });

    mobileNav.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", closeMenu);
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeMenu();
    });
  }

  /* ── Плавный скролл к якорям (с учётом sticky-хедера) ─────────── */
  var header = document.querySelector(".site-header");

  document.querySelectorAll('a[href^="#"]').forEach(function (link) {
    link.addEventListener("click", function (e) {
      var id = link.getAttribute("href");
      if (!id || id === "#") return;
      var target = document.querySelector(id);
      if (!target) return;
      e.preventDefault();
      var headerH = header ? header.offsetHeight : 0;
      var top =
        target.getBoundingClientRect().top +
        window.pageYOffset -
        headerH -
        16;
      window.scrollTo({
        top: top,
        behavior: prefersReducedMotion ? "auto" : "smooth",
      });
      if (history.pushState) history.pushState(null, "", id);
    });
  });

  /* ── Scroll-reveal через IntersectionObserver ─────────────────── */
  var revealEls = document.querySelectorAll(".reveal");

  if (prefersReducedMotion || !("IntersectionObserver" in window)) {
    revealEls.forEach(function (el) {
      el.classList.add("is-visible");
    });
  } else {
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -60px 0px" }
    );

    revealEls.forEach(function (el) {
      // индекс для ступенчатой задержки внутри групп
      var group = el.closest(".reveal-stagger");
      if (group) {
        var children = Array.prototype.slice.call(group.children);
        el.style.setProperty("--i", String(children.indexOf(el)));
      }
      observer.observe(el);
    });
  }

  /* ── Хедер: лёгкая тень/плотность при скролле ─────────────────── */
  if (header) {
    var onScroll = function () {
      if (window.scrollY > 8) {
        header.style.borderBottomColor = "var(--glass-border)";
      } else {
        header.style.borderBottomColor = "transparent";
      }
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }
})();
