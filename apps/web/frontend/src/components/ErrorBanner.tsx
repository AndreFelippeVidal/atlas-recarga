interface Props {
  code: string;
  onRetry: () => void;
}

export default function ErrorBanner({ code, onRetry }: Props) {
  return (
    <div className="banner" role="alert">
      <span>Não foi possível carregar os dados ({code})</span>
      <button type="button" onClick={onRetry}>
        Tentar de novo
      </button>
    </div>
  );
}
