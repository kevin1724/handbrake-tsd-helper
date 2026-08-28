import 'package:flutter/material.dart';

abstract final class ByteSqueezeColors {
  static const ink = Color(0xFFF5F7FB);
  static const softInk = Color(0xFFCCD4DF);
  static const muted = Color(0xFF8C98A8);
  static const canvas = Color(0xFF07090D);
  static const navy = Color(0xFF0B0F16);
  static const shell = Color(0xFF0D121A);
  static const surface = Color(0xFF111720);
  static const raised = Color(0xFF18212D);
  static const line = Color(0xFF273241);
  static const subtleLine = Color(0xFF1C2632);
  static const blue = Color(0xFF7C91FF);
  static const cyan = Color(0xFF48D7E8);
  static const mint = Color(0xFF42D6A0);
  static const amber = Color(0xFFF3B94F);
  static const danger = Color(0xFFFF7185);
  static const violet = Color(0xFFAC8CFF);

  static const backdrop = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFF101722), canvas, Color(0xFF05070A)],
    stops: [0, .46, 1],
  );

  static const commandBackdrop = RadialGradient(
    center: Alignment(-.7, -1.15),
    radius: 1.25,
    colors: [Color(0x3322D3EE), Color(0x00101722)],
  );

  static const brand = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [cyan, blue, violet],
  );
}

abstract final class ByteSqueezeTheme {
  static ThemeData v3({bool compact = false}) =>
      _build(classic: false, compact: compact);

  static ThemeData get classic => _build(classic: true, compact: false);

  static ThemeData get dark => v3();

  static ThemeData _build({required bool classic, required bool compact}) {
    final primary = classic ? ByteSqueezeColors.blue : ByteSqueezeColors.cyan;
    final scheme = ColorScheme.fromSeed(
      seedColor: primary,
      brightness: Brightness.dark,
      surface: ByteSqueezeColors.surface,
      error: ByteSqueezeColors.danger,
    );
    final radius = classic ? 17.0 : (compact ? 12.0 : 14.0);
    final verticalControlPadding = compact ? 10.0 : 12.0;
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: scheme.copyWith(
        primary: primary,
        onPrimary: const Color(0xFF041014),
        secondary: ByteSqueezeColors.blue,
        tertiary: ByteSqueezeColors.violet,
        surface: ByteSqueezeColors.surface,
        surfaceContainer: ByteSqueezeColors.raised,
        outline: ByteSqueezeColors.line,
      ),
      scaffoldBackgroundColor: ByteSqueezeColors.canvas,
      visualDensity: compact ? VisualDensity.compact : VisualDensity.standard,
      textTheme:
          const TextTheme(
            displaySmall: TextStyle(
              fontWeight: FontWeight.w800,
              letterSpacing: -1.4,
            ),
            headlineLarge: TextStyle(
              fontWeight: FontWeight.w800,
              letterSpacing: -.7,
              fontSize: 30,
            ),
            headlineMedium: TextStyle(
              fontWeight: FontWeight.w800,
              letterSpacing: -.7,
            ),
            headlineSmall: TextStyle(
              fontWeight: FontWeight.w700,
              letterSpacing: -.4,
            ),
            titleLarge: TextStyle(
              fontWeight: FontWeight.w700,
              letterSpacing: -.25,
            ),
            titleMedium: TextStyle(fontWeight: FontWeight.w700),
            titleSmall: TextStyle(fontWeight: FontWeight.w700),
            bodyLarge: TextStyle(height: 1.35),
            bodyMedium: TextStyle(height: 1.32),
            labelLarge: TextStyle(fontWeight: FontWeight.w700),
          ).apply(
            bodyColor: ByteSqueezeColors.ink,
            displayColor: ByteSqueezeColors.ink,
          ),
      cardTheme: CardThemeData(
        elevation: 0,
        color: ByteSqueezeColors.surface,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(radius),
          side: BorderSide(
            color: classic
                ? ByteSqueezeColors.line
                : ByteSqueezeColors.subtleLine,
            width: .8,
          ),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: ByteSqueezeColors.surface,
        hintStyle: const TextStyle(color: ByteSqueezeColors.muted),
        labelStyle: const TextStyle(color: ByteSqueezeColors.softInk),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(radius - 4),
          borderSide: BorderSide.none,
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(radius - 4),
          borderSide: const BorderSide(color: ByteSqueezeColors.line),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(radius - 4),
          borderSide: BorderSide(color: primary, width: 1.4),
        ),
        contentPadding: EdgeInsets.symmetric(
          horizontal: 16,
          vertical: verticalControlPadding,
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: const Color(0xFF0B1017),
        surfaceTintColor: Colors.transparent,
        indicatorColor: primary.withValues(alpha: .16),
        indicatorShape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(compact ? 10 : 12),
        ),
        labelTextStyle: const WidgetStatePropertyAll(
          TextStyle(fontWeight: FontWeight.w700, fontSize: 11),
        ),
        height: compact ? 58 : 62,
      ),
      navigationRailTheme: NavigationRailThemeData(
        backgroundColor: ByteSqueezeColors.shell,
        indicatorColor: primary.withValues(alpha: .14),
        selectedIconTheme: IconThemeData(color: primary),
        selectedLabelTextStyle: const TextStyle(
          color: ByteSqueezeColors.ink,
          fontWeight: FontWeight.w700,
        ),
        unselectedLabelTextStyle: const TextStyle(
          color: ByteSqueezeColors.muted,
        ),
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: ByteSqueezeColors.canvas,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        centerTitle: false,
        toolbarHeight: 52,
        titleTextStyle: TextStyle(
          color: ByteSqueezeColors.ink,
          fontSize: 20,
          fontWeight: FontWeight.w800,
          letterSpacing: -.35,
        ),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: ByteSqueezeColors.shell,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      ),
      bottomSheetTheme: const BottomSheetThemeData(
        backgroundColor: ByteSqueezeColors.navy,
        surfaceTintColor: Colors.transparent,
        modalBarrierColor: Color(0xB8000000),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        ),
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: ByteSqueezeColors.raised,
        contentTextStyle: const TextStyle(color: ByteSqueezeColors.ink),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        behavior: SnackBarBehavior.floating,
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          padding: EdgeInsets.symmetric(
            horizontal: compact ? 17 : 20,
            vertical: verticalControlPadding,
          ),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(radius - 4),
          ),
          textStyle: const TextStyle(fontWeight: FontWeight.w700),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          padding: EdgeInsets.symmetric(
            horizontal: compact ? 17 : 20,
            vertical: verticalControlPadding,
          ),
          side: const BorderSide(color: ByteSqueezeColors.line),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(radius - 4),
          ),
        ),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: ByteSqueezeColors.surface,
        selectedColor: primary.withValues(alpha: .14),
        side: const BorderSide(color: ByteSqueezeColors.line),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
        labelStyle: const TextStyle(fontWeight: FontWeight.w600),
      ),
      dividerColor: ByteSqueezeColors.line,
      dividerTheme: const DividerThemeData(
        color: ByteSqueezeColors.subtleLine,
        thickness: 1,
        space: 1,
      ),
      listTileTheme: const ListTileThemeData(
        iconColor: ByteSqueezeColors.softInk,
        textColor: ByteSqueezeColors.ink,
        minVerticalPadding: 8,
      ),
      tooltipTheme: TooltipThemeData(
        decoration: BoxDecoration(
          color: ByteSqueezeColors.raised,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: ByteSqueezeColors.line),
        ),
        textStyle: const TextStyle(color: ByteSqueezeColors.ink, fontSize: 12),
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(
        color: primary,
        linearTrackColor: const Color(0xFF242D3A),
      ),
    );
  }
}
