import {
  Button, Menu, MenuItemRadio, MenuList, MenuPopover, MenuTrigger, Tooltip, makeStyles,
} from '@fluentui/react-components';
import { DesktopRegular, WeatherMoonRegular, WeatherSunnyRegular } from '@fluentui/react-icons';
import { useAppearance } from './AppearanceProvider';

const useStyles = makeStyles({
  trigger: { minWidth: '44px', minHeight: '44px', flexShrink: 0 },
  status: { position: 'absolute', width: '1px', height: '1px', padding: 0, margin: '-1px', overflow: 'hidden', clipPath: 'inset(50%)', whiteSpace: 'nowrap' },
});

const labels = { light: 'Claro', dark: 'Escuro', system: 'Sistema' };

export default function AppearanceMenu() {
  const styles = useStyles();
  const { preference, resolvedTheme, setPreference } = useAppearance();
  const current = preference === 'system' ? `Sistema (${labels[resolvedTheme].toLocaleLowerCase('pt-BR')})` : labels[preference];
  return <>
    <Menu positioning="below-end" checkedValues={{ appearance: [preference] }} onCheckedValueChange={(_, data) => {
      const value = data.checkedItems[0];
      if (value === 'light' || value === 'dark' || value === 'system') setPreference(value);
    }}>
      <MenuTrigger disableButtonEnhancement>
        <Tooltip content={`Aparência: ${current}`} relationship="description">
          <Button appearance="subtle" className={styles.trigger} aria-label="Aparência" icon={preference === 'system' ? <DesktopRegular /> : resolvedTheme === 'dark' ? <WeatherMoonRegular /> : <WeatherSunnyRegular />} />
        </Tooltip>
      </MenuTrigger>
      <MenuPopover><MenuList aria-label="Aparência">
        <MenuItemRadio name="appearance" value="light" icon={<WeatherSunnyRegular />}>Claro</MenuItemRadio>
        <MenuItemRadio name="appearance" value="dark" icon={<WeatherMoonRegular />}>Escuro</MenuItemRadio>
        <MenuItemRadio name="appearance" value="system" icon={<DesktopRegular />}>Sistema</MenuItemRadio>
      </MenuList></MenuPopover>
    </Menu>
    <span className={styles.status} role="status">Aparência: {current}</span>
  </>;
}
