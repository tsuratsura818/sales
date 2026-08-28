/**
 * koharubiyori スキーマの型。
 *
 * 本来は `npm run gen:types`（= supabase gen types typescript --schema koharubiyori）
 * で生成する。Supabase プロジェクトを作る前でも型が通るよう、生成物と同じ形で
 * 手書きしてある。**マイグレーションを適用したら必ず生成し直して上書きすること。**
 * 生成コマンドで --schema を付け忘れると public だけを見て空の型を吐く。
 */

export type Json = string | number | boolean | null | { [key: string]: Json | undefined } | Json[]

export type Database = {
  koharubiyori: {
    Tables: {
      creators: {
        Row: {
          id: string
          slug: string
          name: string
          name_kana: string | null
          title: string | null
          base_area: string | null
          profile: string | null
          tsukumo_note: string | null
          photo_url: string | null
          hero_image_url: string | null
          sns_x: string | null
          sns_instagram: string | null
          website_url: string | null
          ec_url: string | null
          current_tier: Database['koharubiyori']['Enums']['creator_tier'] | null
          status: Database['koharubiyori']['Enums']['publish_status']
          first_engaged_on: string | null
          notes: string | null
          created_at: string
          updated_at: string
        }
        Insert: {
          id?: string
          slug: string
          name: string
          name_kana?: string | null
          title?: string | null
          base_area?: string | null
          profile?: string | null
          tsukumo_note?: string | null
          photo_url?: string | null
          hero_image_url?: string | null
          sns_x?: string | null
          sns_instagram?: string | null
          website_url?: string | null
          ec_url?: string | null
          current_tier?: Database['koharubiyori']['Enums']['creator_tier'] | null
          status?: Database['koharubiyori']['Enums']['publish_status']
          first_engaged_on?: string | null
          notes?: string | null
          created_at?: string
          updated_at?: string
        }
        Update: Partial<Database['koharubiyori']['Tables']['creators']['Insert']>
        Relationships: []
      }
      characters: {
        Row: {
          id: string
          creator_id: string
          slug: string
          name: string
          description: string | null
          hare_ma: Database['koharubiyori']['Enums']['hare_ma'] | null
          image_url: string | null
          status: Database['koharubiyori']['Enums']['publish_status']
          created_at: string
          updated_at: string
        }
        Insert: {
          id?: string
          creator_id: string
          slug: string
          name: string
          description?: string | null
          hare_ma?: Database['koharubiyori']['Enums']['hare_ma'] | null
          image_url?: string | null
          status?: Database['koharubiyori']['Enums']['publish_status']
          created_at?: string
          updated_at?: string
        }
        Update: Partial<Database['koharubiyori']['Tables']['characters']['Insert']>
        Relationships: [
          {
            foreignKeyName: 'characters_creator_id_fkey'
            columns: ['creator_id']
            isOneToOne: false
            referencedRelation: 'creators'
            referencedColumns: ['id']
          },
        ]
      }
      character_scores: {
        Row: {
          id: string
          character_id: string
          scorer_name: string
          q1_line: number
          q2_kurashi: number
          q3_koyomi: number
          q4_taigi: number
          total: number
          comment: string | null
          scored_at: string
        }
        Insert: {
          id?: string
          character_id: string
          scorer_name: string
          q1_line: number
          q2_kurashi: number
          q3_koyomi: number
          q4_taigi: number
          comment?: string | null
          scored_at?: string
        }
        Update: Partial<Database['koharubiyori']['Tables']['character_scores']['Insert']>
        Relationships: [
          {
            foreignKeyName: 'character_scores_character_id_fkey'
            columns: ['character_id']
            isOneToOne: false
            referencedRelation: 'characters'
            referencedColumns: ['id']
          },
        ]
      }
      contracts: {
        Row: {
          id: string
          creator_id: string
          tier: Database['koharubiyori']['Enums']['creator_tier']
          scope: string
          color_adjust_allowed: boolean
          is_exclusive: boolean
          ai_training_prohibited: boolean
          fee_yen: number | null
          revenue_share_pct: number | null
          starts_on: string
          ends_on: string | null
          doc_url: string | null
          notes: string | null
          created_at: string
          updated_at: string
        }
        Insert: {
          id?: string
          creator_id: string
          tier: Database['koharubiyori']['Enums']['creator_tier']
          scope: string
          color_adjust_allowed?: boolean
          is_exclusive?: boolean
          ai_training_prohibited?: boolean
          fee_yen?: number | null
          revenue_share_pct?: number | null
          starts_on: string
          ends_on?: string | null
          doc_url?: string | null
          notes?: string | null
          created_at?: string
          updated_at?: string
        }
        Update: Partial<Database['koharubiyori']['Tables']['contracts']['Insert']>
        Relationships: [
          {
            foreignKeyName: 'contracts_creator_id_fkey'
            columns: ['creator_id']
            isOneToOne: false
            referencedRelation: 'creators'
            referencedColumns: ['id']
          },
        ]
      }
      koyomi_ko: {
        Row: {
          id: number
          slug: string
          name: string
          reading: string
          sekki: string | null
          starts_md: string
          copy: string | null
        }
        Insert: {
          id: number
          slug: string
          name: string
          reading: string
          sekki?: string | null
          starts_md: string
          copy?: string | null
        }
        Update: Partial<Database['koharubiyori']['Tables']['koyomi_ko']['Insert']>
        Relationships: []
      }
      kakegami: {
        Row: {
          id: string
          ko_id: number
          creator_id: string | null
          character_id: string | null
          issue_date: string
          artwork_url: string | null
          print_qty: number | null
          distributed_qty: number | null
          status: Database['koharubiyori']['Enums']['publish_status']
          notes: string | null
          created_at: string
          updated_at: string
        }
        Insert: {
          id?: string
          ko_id: number
          creator_id?: string | null
          character_id?: string | null
          issue_date: string
          artwork_url?: string | null
          print_qty?: number | null
          distributed_qty?: number | null
          status?: Database['koharubiyori']['Enums']['publish_status']
          notes?: string | null
          created_at?: string
          updated_at?: string
        }
        Update: Partial<Database['koharubiyori']['Tables']['kakegami']['Insert']>
        Relationships: [
          {
            foreignKeyName: 'kakegami_ko_id_fkey'
            columns: ['ko_id']
            isOneToOne: false
            referencedRelation: 'koyomi_ko'
            referencedColumns: ['id']
          },
          {
            foreignKeyName: 'kakegami_creator_id_fkey'
            columns: ['creator_id']
            isOneToOne: false
            referencedRelation: 'creators'
            referencedColumns: ['id']
          },
          {
            foreignKeyName: 'kakegami_character_id_fkey'
            columns: ['character_id']
            isOneToOne: false
            referencedRelation: 'characters'
            referencedColumns: ['id']
          },
        ]
      }
      kakegami_scans: {
        Row: {
          id: number
          kakegami_id: string
          scanned_at: string
          referrer: string | null
          user_agent: string | null
          country: string | null
        }
        Insert: {
          kakegami_id: string
          scanned_at?: string
          referrer?: string | null
          user_agent?: string | null
          country?: string | null
        }
        Update: Partial<Database['koharubiyori']['Tables']['kakegami_scans']['Insert']>
        Relationships: [
          {
            foreignKeyName: 'kakegami_scans_kakegami_id_fkey'
            columns: ['kakegami_id']
            isOneToOne: false
            referencedRelation: 'kakegami'
            referencedColumns: ['id']
          },
        ]
      }
      paper_issues: {
        Row: {
          id: string
          issue_no: number
          title: string
          ko_id: number | null
          published_on: string | null
          guest_creator_id: string | null
          feature_maker_id: string | null
          cover_image_url: string | null
          print_qty: number | null
          status: Database['koharubiyori']['Enums']['publish_status']
          notes: string | null
          created_at: string
          updated_at: string
        }
        Insert: {
          id?: string
          issue_no: number
          title: string
          ko_id?: number | null
          published_on?: string | null
          guest_creator_id?: string | null
          feature_maker_id?: string | null
          cover_image_url?: string | null
          print_qty?: number | null
          status?: Database['koharubiyori']['Enums']['publish_status']
          notes?: string | null
          created_at?: string
          updated_at?: string
        }
        Update: Partial<Database['koharubiyori']['Tables']['paper_issues']['Insert']>
        Relationships: [
          {
            foreignKeyName: 'paper_issues_ko_id_fkey'
            columns: ['ko_id']
            isOneToOne: false
            referencedRelation: 'koyomi_ko'
            referencedColumns: ['id']
          },
          {
            foreignKeyName: 'paper_issues_guest_creator_id_fkey'
            columns: ['guest_creator_id']
            isOneToOne: false
            referencedRelation: 'creators'
            referencedColumns: ['id']
          },
          {
            foreignKeyName: 'paper_issues_feature_maker_id_fkey'
            columns: ['feature_maker_id']
            isOneToOne: false
            referencedRelation: 'creators'
            referencedColumns: ['id']
          },
        ]
      }
    }
    Views: {
      character_verdicts: {
        Row: {
          character_id: string | null
          creator_id: string | null
          scorer_count: number | null
          avg_total: number | null
          min_q3: number | null
          verdict: Database['koharubiyori']['Enums']['score_verdict'] | null
          is_confirmable: boolean | null
        }
        Relationships: []
      }
      kakegami_stats: {
        Row: {
          kakegami_id: string | null
          ko_id: number | null
          issue_date: string | null
          creator_id: string | null
          distributed_qty: number | null
          scan_count: number | null
          scan_rate_pct: number | null
        }
        Relationships: []
      }
    }
    Functions: Record<never, never>
    Enums: {
      hare_ma: 'asa' | 'hitoiki' | 'yoru' | 'dekakeru' | 'kazaru' | 'sodateru'
      creator_tier: 'tier1' | 'tier2' | 'tier3'
      score_verdict: 'adopt' | 'trial' | 'hold' | 'reject'
      publish_status: 'draft' | 'published' | 'archived'
    }
    CompositeTypes: Record<never, never>
  }
}

type Schema = Database['koharubiyori']

export type Tables<T extends keyof Schema['Tables']> = Schema['Tables'][T]['Row']
export type TablesInsert<T extends keyof Schema['Tables']> = Schema['Tables'][T]['Insert']
export type TablesUpdate<T extends keyof Schema['Tables']> = Schema['Tables'][T]['Update']
export type Views<T extends keyof Schema['Views']> = Schema['Views'][T]['Row']
export type Enums<T extends keyof Schema['Enums']> = Schema['Enums'][T]
