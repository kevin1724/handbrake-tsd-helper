import 'package:flutter/material.dart';

abstract final class ByteSqueezeColors {
  static const ink = Color(0xFFF4F8FF);
  static const muted = Color(0xFF91A4C7);
  static const canvas = Color(0xFF040A16);
  static const navy = Color(0xFF071329);
  static const surface = Color(0xFF0C1A34);
  static const raised = Color(0xFF112445);
  static const line = Color(0xFF1D355D);
  static const blue = Color(0xFF258BFF);
  static const cyan = Color(0xFF31D6FF);
  static const mint = Color(0xFF43E1AE);
  static const amber = Color(0xFFFFC857);
  static const danger = Color(0xFFFF6B7A);

  static const backdrop = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFF07152E), canvas, Color(0xFF02060E)],
    stops: [0, .55, 1],
  );

  static const brand = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFF39D8FF), Color(0xFF267DFF), Color(0xFF1640C9)],
  );
}

abstract final class ByteSqueezeTheme {
  static ThemeData get dark {
    final scheme = ColorScheme.fromSeed(
      seedColor: ByteSqueezeColors.blue,
      brightness: Brightness.dark,
      surface: ByteSqueezeColors.surface,
      error: ByteSqueezeColors.danger,
    );
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: scheme.copyWith(
        primary: ByteSqueezeColors.blue,
        secondary: ByteSqueezeColors.cyan,
        surface: ByteSqueezeColors.surface,
        outline: ByteSqueezeColors.line,
      ),
      scaffoldBackgroundColor: ByteSqueezeColors.canvas,
      fontFamily: 'sans-serif',
      textTheme: const TextTheme(
        displaySmall:
            TextStyle(fontWeight: FontWeight.w800, letterSpacing: -1.5),
        headlineLarge:
            TextStyle(fontWeight: FontWeight.w800, letterSpacing: -1.1),
        headlineMedium:
            TextStyle(fontWeight: FontWeight.w800, letterSpacing: -.8),
        headlineSmall:
            TextStyle(fontWeight: FontWeight.w700, letterSpacing: -.5),
        titleLarge: TextStyle(fontWeight: FontWeight.w700, letterSpacing: -.3),
        titleMedium: TextStyle(fontWeight: FontWeight.w700),
        bodyLarge: TextStyle(height: 1.35),
        bodyMedium: TextStyle(height: 1.35),
      ).apply(
          bodyColor: ByteSqueezeColors.ink,
          displayColor: ByteSqueezeColors.ink),
      cardTheme: CardThemeData(
        elevation: 0,
        color: ByteSqueezeColors.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(22),
          side: const BorderSide(color: ByteSqueezeColors.line, width: .7),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: ByteSqueezeColors.surface,
        hintStyle: const TextStyle(color: ByteSqueezeColors.muted),
        border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(16),
            borderSide: BorderSide.none),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: ByteSqueezeColors.line),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide:
              const BorderSide(color: ByteSqueezeColors.cyan, width: 1.4),
        ),
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
      ),
      navigationBarTheme: const NavigationBarThemeData(
        backgroundColor: Color(0xF20A1427),
        indicatorColor: Color(0xFF164D7E),
        indicatorShape: StadiumBorder(),
        labelTextStyle: WidgetStatePropertyAll(
            TextStyle(fontWeight: FontWeight.w600, fontSize: 12)),
        height: 74,
      ),
      navigationRailTheme: const NavigationRailThemeData(
        backgroundColor: Color(0xFF071329),
        indicatorColor: Color(0x33258BFF),
        selectedIconTheme: IconThemeData(color: ByteSqueezeColors.cyan),
        selectedLabelTextStyle: TextStyle(
            color: ByteSqueezeColors.ink, fontWeight: FontWeight.w700),
        unselectedLabelTextStyle: TextStyle(color: ByteSqueezeColors.muted),
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.transparent,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: ByteSqueezeColors.raised,
        contentTextStyle: const TextStyle(color: ByteSqueezeColors.ink),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        behavior: SnackBarBehavior.floating,
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 15),
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          textStyle: const TextStyle(fontWeight: FontWeight.w700),
        ),
      ),
      dividerColor: ByteSqueezeColors.line,
      progressIndicatorTheme: const ProgressIndicatorThemeData(
        color: ByteSqueezeColors.cyan,
        linearTrackColor: Color(0xFF172A4D),
      ),
    );
  }
}
