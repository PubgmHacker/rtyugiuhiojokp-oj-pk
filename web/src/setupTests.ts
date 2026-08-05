/**
 * jsdom не реализует scrollIntoView — экраны чатов вызывают его при каждом
 * новом сообщении, без заглушки любой такой тест падает не из-за бага,
 * а из-за отсутствия DOM API в среде тестов.
 */
import "@testing-library/jest-dom/vitest";

if (!("scrollIntoView" in Element.prototype)) {
  (Element.prototype as { scrollIntoView: () => void }).scrollIntoView =
    function scrollIntoView() {};
}
