export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.18"
  }
  public: {
    Tables: {
      cities: {
        Row: {
          active: boolean
          boundary_source_id: string | null
          city_code: string
          created_at: string
          h3_resolution: number
          ibge_code: string
          name: string
          service_radius_m: number
          state: string
          transit_radius_m: number
        }
        Insert: {
          active?: boolean
          boundary_source_id?: string | null
          city_code: string
          created_at?: string
          h3_resolution?: number
          ibge_code: string
          name: string
          service_radius_m?: number
          state: string
          transit_radius_m?: number
        }
        Update: {
          active?: boolean
          boundary_source_id?: string | null
          city_code?: string
          created_at?: string
          h3_resolution?: number
          ibge_code?: string
          name?: string
          service_radius_m?: number
          state?: string
          transit_radius_m?: number
        }
        Relationships: []
      }
      discovered_layers: {
        Row: {
          approved: boolean
          city_code: string
          count_error: string | null
          discovered_at: string
          endpoint_url: string
          feature_count: number | null
          id: string
          layer_name: string
          matched_terms: string[]
          title: string | null
        }
        Insert: {
          approved?: boolean
          city_code: string
          count_error?: string | null
          discovered_at?: string
          endpoint_url: string
          feature_count?: number | null
          id?: string
          layer_name: string
          matched_terms?: string[]
          title?: string | null
        }
        Update: {
          approved?: boolean
          city_code?: string
          count_error?: string | null
          discovered_at?: string
          endpoint_url?: string
          feature_count?: number | null
          id?: string
          layer_name?: string
          matched_terms?: string[]
          title?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "discovered_layers_city_code_fkey"
            columns: ["city_code"]
            isOneToOne: false
            referencedRelation: "cities"
            referencedColumns: ["city_code"]
          },
        ]
      }
      run_logs: {
        Row: {
          city_code: string | null
          created_at: string
          details: Json | null
          id: number
          level: string
          message: string
          run_id: string | null
          source_id: string | null
        }
        Insert: {
          city_code?: string | null
          created_at?: string
          details?: Json | null
          id?: number
          level?: string
          message: string
          run_id?: string | null
          source_id?: string | null
        }
        Update: {
          city_code?: string | null
          created_at?: string
          details?: Json | null
          id?: number
          level?: string
          message?: string
          run_id?: string | null
          source_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "run_logs_run_id_fkey"
            columns: ["run_id"]
            isOneToOne: false
            referencedRelation: "runs"
            referencedColumns: ["run_id"]
          },
        ]
      }
      runs: {
        Row: {
          city_code: string
          cursor: Json | null
          finished_at: string | null
          run_id: string
          started_at: string
          status: string
          step: string
          summary: Json | null
        }
        Insert: {
          city_code: string
          cursor?: Json | null
          finished_at?: string | null
          run_id?: string
          started_at?: string
          status?: string
          step: string
          summary?: Json | null
        }
        Update: {
          city_code?: string
          cursor?: Json | null
          finished_at?: string | null
          run_id?: string
          started_at?: string
          status?: string
          step?: string
          summary?: Json | null
        }
        Relationships: [
          {
            foreignKeyName: "runs_city_code_fkey"
            columns: ["city_code"]
            isOneToOne: false
            referencedRelation: "cities"
            referencedColumns: ["city_code"]
          },
        ]
      }
      sources: {
        Row: {
          approved: boolean
          category: string | null
          city_code: string
          created_at: string
          endpoint_url: string
          geometry_hint: string | null
          layer: string | null
          name: string
          notes: string | null
          protocol: string
          publisher: string
          role: string
          source_id: string
          subcategory: string | null
          type_name: string | null
          updated_at: string
          verified_at: string | null
          verified_in_capabilities: boolean | null
        }
        Insert: {
          approved?: boolean
          category?: string | null
          city_code: string
          created_at?: string
          endpoint_url: string
          geometry_hint?: string | null
          layer?: string | null
          name: string
          notes?: string | null
          protocol: string
          publisher: string
          role?: string
          source_id: string
          subcategory?: string | null
          type_name?: string | null
          updated_at?: string
          verified_at?: string | null
          verified_in_capabilities?: boolean | null
        }
        Update: {
          approved?: boolean
          category?: string | null
          city_code?: string
          created_at?: string
          endpoint_url?: string
          geometry_hint?: string | null
          layer?: string | null
          name?: string
          notes?: string | null
          protocol?: string
          publisher?: string
          role?: string
          source_id?: string
          subcategory?: string | null
          type_name?: string | null
          updated_at?: string
          verified_at?: string | null
          verified_in_capabilities?: boolean | null
        }
        Relationships: [
          {
            foreignKeyName: "sources_city_code_fkey"
            columns: ["city_code"]
            isOneToOne: false
            referencedRelation: "cities"
            referencedColumns: ["city_code"]
          },
        ]
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      [_ in never]: never
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends (DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never) = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends (PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never) = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {},
  },
} as const
