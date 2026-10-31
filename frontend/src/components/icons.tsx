/** App-wide icons: Phosphor duotone, under the short names the pages use. Change the look of every icon here. */
import {
  AddressBook,
  ArrowCounterClockwise,
  ArrowLeft as PhArrowLeft,
  ArrowRight as PhArrowRight,
  ArrowsClockwise,
  ArrowUUpLeft,
  Archive as PhArchive,
  Bell as PhBell,
  Broadcast,
  Calculator as PhCalculator,
  CalendarBlank,
  Camera as PhCamera,
  CaretRight,
  ChartLineUp as PhChartLineUp,
  ChatsCircle,
  CheckCircle,
  Check as PhCheck,
  CircleNotch,
  ClipboardText,
  ClockCounterClockwise,
  CloudArrowUp,
  Columns as PhColumns,
  Database,
  DownloadSimple,
  Eye as PhEye,
  EyeSlash,
  FileArrowUp,
  FilePdf as PhFilePdf,
  FileText as PhFileText,
  FloppyDisk,
  FlowArrow as PhFlowArrow,
  Funnel as PhFunnel,
  GearSix,
  GlobeHemisphereWest,
  HourglassMedium as PhHourglassMedium,
  ImageSquare,
  Info as PhInfo,
  Kanban as PhKanban,
  Key,
  List,
  LockSimple,
  MagnifyingGlass,
  Moon as PhMoon,
  NotePencil,
  Package as PhPackage,
  PaperPlaneTilt,
  Paperclip as PhPaperclip,
  PencilSimple,
  Phone as PhPhone,
  PlayCircle as PhPlayCircle,
  Plus as PhPlus,
  Power as PhPower,
  Printer as PhPrinter,
  Ranking as PhRanking,
  SealCheck as PhSealCheck,
  ShieldSlash,
  SignIn,
  SignOut,
  Sparkle,
  SquaresFour,
  Sun as PhSun,
  Table as PhTable,
  Trash,
  Tray,
  Truck as PhTruck,
  UploadSimple,
  UserCircle,
  UserPlus as PhUserPlus,
  UsersThree,
  Warning,
  WarningCircle,
  X as PhX,
  XCircle as PhXCircle,
  type Icon,
  type IconProps,
} from "@phosphor-icons/react";

const duo = (Glyph: Icon) => (props: IconProps) => <Glyph weight="duotone" {...props} />;
/** Thin line glyphs: duotone shading behind these reads as a smudge at small sizes. */
const line = (Glyph: Icon) => (props: IconProps) => <Glyph weight="bold" {...props} />;

export const AlertCircle = duo(WarningCircle);
export const AlertTriangle = duo(Warning);
export const Archive = duo(PhArchive);
export const ArchiveRestore = duo(ArrowUUpLeft);
export const ArrowLeft = line(PhArrowLeft);
export const ArrowRight = line(PhArrowRight);
export const Bell = duo(PhBell);
export const Calculator = duo(PhCalculator);
export const Calendar = duo(CalendarBlank);
export const Camera = duo(PhCamera);
export const ChartLineUp = duo(PhChartLineUp);
export const Check = line(PhCheck);
export const CheckCircle2 = duo(CheckCircle);
export const ChevronRight = line(CaretRight);
export const ClipboardList = duo(ClipboardText);
export const Columns = duo(PhColumns);
export const Contact = duo(AddressBook);
export const DatabaseBackup = duo(Database);
export const Download = duo(DownloadSimple);
export const Eye = duo(PhEye);
export const EyeOff = duo(EyeSlash);
export const FilePdf = duo(PhFilePdf);
export const FilePen = duo(NotePencil);
export const FileText = duo(PhFileText);
export const FileUp = duo(FileArrowUp);
export const FlowArrow = duo(PhFlowArrow);
export const Funnel = duo(PhFunnel);
export const Globe2 = duo(GlobeHemisphereWest);
export const History = duo(ClockCounterClockwise);
export const Hourglass = duo(PhHourglassMedium);
export const ImagePlus = duo(ImageSquare);
export const Inbox = duo(Tray);
export const Info = duo(PhInfo);
export const Kanban = duo(PhKanban);
export const KeyRound = duo(Key);
export const LayoutDashboard = duo(SquaresFour);
export const Loader2 = line(CircleNotch);
export const Lock = duo(LockSimple);
export const LogIn = duo(SignIn);
export const LogOut = duo(SignOut);
export const Menu = line(List);
export const MessageSquare = duo(ChatsCircle);
export const Moon = duo(PhMoon);
export const Package = duo(PhPackage);
export const Paperclip = line(PhPaperclip);
export const Pencil = duo(PencilSimple);
export const Phone = duo(PhPhone);
export const PlayCircle = duo(PhPlayCircle);
export const Plus = line(PhPlus);
export const Power = duo(PhPower);
export const Printer = duo(PhPrinter);
export const Radio = duo(Broadcast);
export const Ranking = duo(PhRanking);
export const RefreshCw = line(ArrowsClockwise);
export const RotateCcw = line(ArrowCounterClockwise);
export const Save = duo(FloppyDisk);
export const SealCheck = duo(PhSealCheck);
export const Search = line(MagnifyingGlass);
export const Send = duo(PaperPlaneTilt);
export const Settings = duo(GearSix);
export const ShieldOff = duo(ShieldSlash);
export const Sparkles = duo(Sparkle);
export const Sun = duo(PhSun);
export const Table = duo(PhTable);
export const Trash2 = duo(Trash);
export const Truck = duo(PhTruck);
export const Upload = duo(UploadSimple);
export const UploadCloud = duo(CloudArrowUp);
export const User = duo(UserCircle);
export const UserPlus = duo(PhUserPlus);
export const Users = duo(UsersThree);
export const X = line(PhX);
export const XCircle = duo(PhXCircle);
