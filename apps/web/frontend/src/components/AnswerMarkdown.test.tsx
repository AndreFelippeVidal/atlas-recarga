import { render, screen } from "@testing-library/react";
import AnswerMarkdown, { splitSource } from "./AnswerMarkdown";

it("renderiza negrito sem deixar os asteriscos", () => {
  render(<AnswerMarkdown text="A receita de **outubro de 2026** foi de **R$ 4.122.460,00**." />);
  expect(screen.getByText("outubro de 2026").tagName).toBe("STRONG");
  expect(screen.getByText("R$ 4.122.460,00").tagName).toBe("STRONG");
  expect(document.body.textContent).not.toContain("**");
});

it("renderiza lista e tabela (GFM)", () => {
  render(<AnswerMarkdown text={"- SP\n- RJ\n\n| UF | Receita |\n|---|---|\n| SP | 1 |"} />);
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
  expect(screen.getByRole("table")).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Receita" })).toBeInTheDocument();
});

it("não deixa HTML cru chegar ao DOM", () => {
  const { container } = render(
    <AnswerMarkdown text={'oi <script>window.x=1</script><img src=x onerror="window.x=1"> fim'} />,
  );
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector("img")).toBeNull();
  expect(container.innerHTML).not.toContain("onerror");
});

it("descarta links javascript: e imagens em Markdown", () => {
  const { container } = render(
    <AnswerMarkdown text={"[clique](javascript:alert(1)) e ![x](https://e.com/a.png)"} />,
  );
  expect(container.querySelector("a")).toBeNull();
  expect(container.querySelector("img")).toBeNull();
  expect(screen.getByText("clique")).toBeInTheDocument();
});

it("links http(s) abrem em outra aba, sem opener", () => {
  render(<AnswerMarkdown text="veja [docs](https://example.com/x)" />);
  const a = screen.getByRole("link", { name: "docs" });
  expect(a).toHaveAttribute("href", "https://example.com/x");
  expect(a).toHaveAttribute("target", "_blank");
  expect(a).toHaveAttribute("rel", "noopener noreferrer");
});

it("destaca o bloco Fonte: sem mudar o texto", () => {
  const text =
    "Foi de **R$ 4.122.460,00**.\n\nFonte: semantic.mv_recharges · gross_revenue · 2026-10";
  render(<AnswerMarkdown text={text} />);
  expect(screen.getByLabelText("Fonte da resposta")).toHaveTextContent(
    "Fonte: semantic.mv_recharges · gross_revenue · 2026-10",
  );
  expect(screen.getByText("R$ 4.122.460,00")).toBeInTheDocument();
});

it("splitSource usa a última Fonte: e aceita resposta sem ela", () => {
  expect(splitSource("só texto")).toEqual({ body: "só texto", source: "" });
  expect(splitSource("a\nFonte: x\nb Fonte: y")).toEqual({
    body: "a",
    source: "Fonte: x\nb Fonte: y",
  });
});

it("negrito sem par (streaming) não quebra nem vaza elemento", () => {
  const { container } = render(<AnswerMarkdown text="A receita foi de **R$ 4.122" />);
  expect(container.querySelector("strong")).toBeNull();
  expect(container.textContent).toContain("R$ 4.122");
});

it("resposta sem Fonte: não mostra a citação", () => {
  render(<AnswerMarkdown text="Não tenho esse dado." />);
  expect(screen.queryByLabelText("Fonte da resposta")).toBeNull();
  expect(screen.getByText("Não tenho esse dado.")).toBeInTheDocument();
});

it("Fonte: com Markdown dentro e a variante **Fonte:**", () => {
  const { container, unmount } = render(
    <AnswerMarkdown text={"ok\n\nFonte: `semantic.mv_recharges` · **gross_revenue**"} />,
  );
  const aside = screen.getByLabelText("Fonte da resposta");
  expect(aside.querySelector("code")?.textContent).toBe("semantic.mv_recharges");
  expect(container.textContent).not.toContain("`");
  unmount();

  render(<AnswerMarkdown text={"ok\n\n**Fonte:** semantic.mv_recharges"} />);
  expect(screen.getByLabelText("Fonte da resposta")).toHaveTextContent(
    "Fonte: semantic.mv_recharges",
  );
});
