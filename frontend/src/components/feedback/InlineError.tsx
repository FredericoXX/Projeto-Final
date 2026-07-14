export function InlineError({ id, message }: { id?: string; message: string }) {
  return (
    <p id={id} className="inline-error" role="alert">
      {message}
    </p>
  );
}
