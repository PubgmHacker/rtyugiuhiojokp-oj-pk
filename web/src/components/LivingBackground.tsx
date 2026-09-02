/**
 * Живой фон — свет за интерфейсом, по мотивам V4LivingBackground из Plink.
 *
 * Сцена из пяти слоёв: купол (ровная подсветка сверху тоном акцента), три
 * эллиптических орба цвета схемы, искра — маленький светлый источник
 * контрастного оттенка, зерно и вертикальная тень. Орбы плывут каждый в
 * своих фазах (сдвиг, дыхание, поворот) с разными периодами — фазы никогда
 * не совпадают, и движение читается как живое, а не как зацикленный ролик.
 * Тень внизу плотная, чтобы списки и подписи читались на ровной канве.
 *
 * Слой монтируется один раз в App и лежит на z-index −1 под #root: html
 * залит цветом схемы, body и #root прозрачны (см. globals.css). Цвета
 * приезжают переменными --orb-1…3 и --spark с <html> — их ставит
 * applyAppearance, поэтому смена схемы перекрашивает фон без единого
 * рендера React.
 *
 * Анимируются только `translate`/`scale`/`rotate` — композитные свойства,
 * без filter: размытие даёт сам радиальный градиент, зерно — одна
 * SVG-плитка. На WebView Telegram и Capacitor это единственный способ
 * держать 60 к/с с несколькими слоями во весь экран. Схемы без орбов
 * («День», «Сепия») выключают слой атрибутом data-living="off";
 * «Уменьшить движение» и тумблер «Живое движение» замораживают сцену.
 */
export function LivingBackground() {
  return (
    <div className="living-bg" aria-hidden="true">
      <i className="living-bg__dome" />
      <div className="living-bg__canvas">
        <i className="living-bg__orb living-bg__orb--1" />
        <i className="living-bg__orb living-bg__orb--2" />
        <i className="living-bg__orb living-bg__orb--3" />
        <i className="living-bg__spark" />
      </div>
      <i className="living-bg__grain" />
      <i className="living-bg__scrim" />
    </div>
  );
}
