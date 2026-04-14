interface Props {
  onClick: () => void
  label?: string
}

export default function BackButton({ onClick, label = '← 뒤로' }: Props) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1 text-gray-500 text-base font-medium py-2 px-1 active:opacity-60 transition-opacity"
    >
      {label}
    </button>
  )
}
