import 'package:flutter/material.dart';

abstract final class ByteSqueezeColors {
  static const ink = Color(0xFFF4F7FB);
  static const muted = Color(0xFF929EAE);
  static const canvas = Color(0xFF07090D);
  static const navy = Color(0xFF0C1017);
  static const surface = Color(0xFF10151D);
  static const raised = Color(0xFF171E29);
  static const line = Color(0xFF283240);
  static const blue = Color(0xFF7790FF);
  static const cyan = Color(0xFF4DD7E7);
  static const mint = Color(0xFF46D6A3);
  static const amber = Color(0xFFF5BB4D);
  static const danger = Color(0xFFFF7185);

  static const backdrop = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFF101520), canvas, Color(0xFF05070A)],
    stops: [0, .48, 1],
  );

  static const brand = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [cyan, Color(0xFF7790FF), Color(0xFFA78BFA)],
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
          borderRadius: BorderRadius.circular(17),
          side: const BorderSide(color: ByteSqueezeColors.line, width: .7),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: ByteSqueezeColors.surface,
        hintStyle: const TextStyle(color: ByteSqueezeColors.muted),
        border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(13),
            borderSide: BorderSide.none),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(13),
          borderSide: const BorderSide(color: ByteSqueezeColors.line),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(13),
          borderSide:
              const BorderSide(color: ByteSqueezeColors.cyan, width: 1.4),
        ),
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
      ),
      navigationBarTheme: const NavigationBarThemeData(
        backgroundColor: Color(0xF20C1118),
        indicatorColor: Color(0xFF173841),
        indicatorShape: StadiumBorder(),
        labelTextStyle: WidgetStatePropertyAll(
            TextStyle(fontWeight: FontWeight.w600, fontSize: 12)),
        height: 74,
      ),
      navigationRailTheme: const NavigationRailThemeData(
        backgroundColor: Color(0xFF0C1017),
        indicatorColor: Color(0x334DD7E7),
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
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(13)),
        behavior: SnackBarBehavior.floating,
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 15),
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(13)),
          textStyle: const TextStyle(fontWeight: FontWeight.w700),
        ),
      ),
      dividerColor: ByteSqueezeColors.line,
      progressIndicatorTheme: const ProgressIndicatorThemeData(
        color: ByteSqueezeColors.cyan,
        linearTrackColor: Color(0xFF242D3A),
      ),
    );
  }
}
