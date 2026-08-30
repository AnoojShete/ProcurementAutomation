function timeOfDayGreeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

export function Greeting({ name, subtitle }: { name: string; subtitle: string }) {
  return (
    <div>
      <h1 className="text-2xl font-semibold text-slate-900">
        {timeOfDayGreeting()}, {name}
      </h1>
      <p className="mt-1 text-sm text-slate-500">{subtitle}</p>
    </div>
  );
}
